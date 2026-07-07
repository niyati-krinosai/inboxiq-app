import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.article import Article, CanonicalEvent
from app.models.knowledge_graph import EntityRelation, KnowledgeEntity

log = get_logger(__name__)

ENTITY_FIELDS = [
    ("company", "companies"),
    ("product", "products"),
    ("framework", "frameworks"),
    ("api", "apis"),
    ("model", "models"),
    ("person", "people"),
    ("repository", "repositories"),
]


async def _upsert_entity(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: str,
    name: str,
    canonical_event_id: uuid.UUID | None,
    now: datetime,
) -> KnowledgeEntity:
    result = await db.execute(
        select(KnowledgeEntity).where(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.entity_type == entity_type,
            KnowledgeEntity.name == name,
        )
    )
    entity = result.scalar_one_or_none()
    if entity:
        entity.last_seen_at = now
        if canonical_event_id:
            entity.canonical_event_id = canonical_event_id
        return entity

    entity = KnowledgeEntity(
        user_id=user_id,
        entity_type=entity_type,
        name=name,
        canonical_event_id=canonical_event_id,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(entity)
    await db.flush()
    return entity


async def build_graph_from_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    event: CanonicalEvent,
) -> None:
    """Phase 9: connect entities from a canonical event into a knowledge graph."""
    now = datetime.now(timezone.utc)
    entities: dict[tuple[str, str], KnowledgeEntity] = {}

    for entity_type, field in ENTITY_FIELDS:
        values = getattr(event, field, None) or []
        for name in values:
            if not name or not isinstance(name, str):
                continue
            key = (entity_type, name)
            entities[key] = await _upsert_entity(db, user_id, entity_type, name, event.id, now)

    # Company -> product/model/api relations
    companies = [entities[k] for k in entities if k[0] == "company"]
    products = [entities[k] for k in entities if k[0] in ("product", "model", "api", "framework")]

    for company in companies:
        for product in products:
            await _add_relation(db, user_id, company.id, product.id, "announced", event.id)

    log.debug("knowledge_graph_updated", event_id=str(event.id), entities=len(entities))


async def _add_relation(
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
