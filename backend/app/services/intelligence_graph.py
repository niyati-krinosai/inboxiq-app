"""Phase 25: Event-centric intelligence graph."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.article import CanonicalEvent
from app.models.knowledge_graph import EntityRelation, KnowledgeEntity
from app.services.knowledge_graph import build_graph_from_event

log = get_logger(__name__)

RELATION_CHAINS = [
    ("company", "announced", "product"),
    ("company", "released", "model"),
    ("product", "uses", "api"),
    ("product", "part_of", "framework"),
    ("framework", "documented_in", "documentation"),
    ("product", "hosted_on", "repository"),
]


async def expand_event_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    event: CanonicalEvent,
) -> None:
    """Build event-centric graph: Company → Product → API → SDK → Docs → Newsletter sources."""
    await build_graph_from_event(db, user_id, event)

    now = datetime.now(timezone.utc)
    entities: dict[tuple[str, str], KnowledgeEntity] = {}

    for entity_type, field in [
        ("company", event.companies),
        ("product", event.products),
        ("model", event.models),
        ("api", event.apis),
        ("framework", event.frameworks),
        ("repository", event.repositories),
        ("technology", event.technologies),
    ]:
        for name in (field or []):
            if not isinstance(name, str):
                continue
            key = (entity_type, name)
            if key in entities:
                continue
            result = await db.execute(
                select(KnowledgeEntity).where(
                    KnowledgeEntity.user_id == user_id,
                    KnowledgeEntity.entity_type == entity_type,
                    KnowledgeEntity.name == name,
                )
            )
            entity = result.scalar_one_or_none()
            if not entity:
                entity = KnowledgeEntity(
                    user_id=user_id,
                    entity_type=entity_type,
                    name=name,
                    canonical_event_id=event.id,
                    first_seen_at=now,
                    last_seen_at=now,
                    metadata_json={"event_title": event.canonical_title or event.headline},
                )
                db.add(entity)
                await db.flush()
            entities[key] = entity

    # Chain relations: company → product → api
    companies = [entities[k] for k in entities if k[0] == "company"]
    products = [entities[k] for k in entities if k[0] in ("product", "model")]
    apis = [entities[k] for k in entities if k[0] == "api"]
    repos = [entities[k] for k in entities if k[0] == "repository"]

    for company in companies:
        for product in products:
            await _link(db, user_id, company.id, product.id, "announced", event.id)
        for api in apis:
            await _link(db, user_id, company.id, api.id, "released", event.id)

    for product in products:
        for api in apis:
            await _link(db, user_id, product.id, api.id, "uses", event.id)
        for repo in repos:
            await _link(db, user_id, product.id, repo.id, "hosted_on", event.id)

    # Link event headline as topic node
    topic_name = event.canonical_title or event.headline
    topic_key = ("topic", topic_name[:200])
    if topic_key not in entities:
        topic = KnowledgeEntity(
            user_id=user_id,
            entity_type="topic",
            name=topic_name[:200],
            canonical_event_id=event.id,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(topic)
        await db.flush()
        entities[topic_key] = topic

    for company in companies:
        await _link(db, user_id, company.id, entities[topic_key].id, "related_to", event.id)

    await db.flush()


async def _link(
    db: AsyncSession,
    user_id: uuid.UUID,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    relation_type: str,
    event_id: uuid.UUID,
) -> None:
    existing = await db.execute(
        select(EntityRelation).where(
            EntityRelation.user_id == user_id,
            EntityRelation.source_id == source_id,
            EntityRelation.target_id == target_id,
            EntityRelation.relation_type == relation_type,
        )
    )
    if existing.scalar_one_or_none():
        return
    db.add(EntityRelation(
        user_id=user_id,
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        canonical_event_id=event_id,
    ))


async def get_event_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
) -> dict:
    """Return event-centric subgraph for exploration."""
    entities_result = await db.execute(
        select(KnowledgeEntity).where(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.canonical_event_id == event_id,
        )
    )
    entities = list(entities_result.scalars().all())
    entity_ids = [e.id for e in entities]

    relations = []
    if entity_ids:
        rel_result = await db.execute(
            select(EntityRelation).where(
                EntityRelation.user_id == user_id,
                EntityRelation.source_id.in_(entity_ids),
            )
        )
        relations = list(rel_result.scalars().all())

    return {
        "entities": [
            {"id": str(e.id), "type": e.entity_type, "name": e.name}
            for e in entities
        ],
        "relations": [
            {
                "source": str(r.source_id),
                "target": str(r.target_id),
                "type": r.relation_type,
            }
            for r in relations
        ],
    }
