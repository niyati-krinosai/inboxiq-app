"""Phase 22: Company intelligence pages."""

import uuid

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import CanonicalEvent
from app.models.knowledge_graph import EntityRelation, KnowledgeEntity


async def get_company_intelligence(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
) -> dict:
    pattern = f"%{company_name}%"

    # Events mentioning this company
    events_result = await db.execute(
        select(CanonicalEvent)
        .where(
            CanonicalEvent.user_id == user_id,
            cast(CanonicalEvent.companies, String).ilike(pattern),
        )
        .options(selectinload(CanonicalEvent.sources))
        .order_by(CanonicalEvent.ranking_score.desc().nullslast())
        .limit(50)
    )
    events = list(events_result.scalars().all())

    # Knowledge graph entity
    entity_result = await db.execute(
        select(KnowledgeEntity).where(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.entity_type == "company",
            KnowledgeEntity.name.ilike(pattern),
        )
    )
    entities = list(entity_result.scalars().all())

    # Related entities via graph
    related: list[dict] = []
    for entity in entities:
        rel_result = await db.execute(
            select(EntityRelation).where(EntityRelation.source_id == entity.id)
        )
        for rel in rel_result.scalars().all():
            target = await db.get(KnowledgeEntity, rel.target_id)
            if target:
                related.append({
                    "name": target.name,
                    "type": target.entity_type,
                    "relation": rel.relation_type,
                })

    # Aggregate entities across events
    models, products, apis, repos, funding = set(), set(), set(), set(), set()
    for e in events:
        for m in (e.models or []):
            models.add(m)
        for p in (e.products or []):
            products.add(p)
        for a in (e.apis or []):
            apis.add(a)
        for r in (e.repositories or []):
            repos.add(r)

    timeline = [
        {
            "date": e.published_at.isoformat() if e.published_at else None,
            "headline": e.headline,
            "canonical_title": e.canonical_title,
            "event_type": e.event_type,
            "ranking_score": e.ranking_score,
            "official_link": e.official_link,
        }
        for e in events
    ]

    newsletter_mentions = []
    for e in events:
        for s in (e.sources or []):
            newsletter_mentions.append({
                "newsletter": s.newsletter_name,
                "headline": e.headline,
                "summary": s.summary_snippet,
            })

    official_blogs = [
        {"url": e.official_link, "headline": e.headline}
        for e in events if e.official_link
    ]

    return {
        "company": company_name,
        "event_count": len(events),
        "timeline": timeline,
        "models": list(models),
        "products": list(products),
        "apis": list(apis),
        "repositories": list(repos),
        "funding": list(funding),
        "announcements": [
            {
                "headline": e.headline,
                "summary": e.primary_summary,
                "verification": e.verification_level,
                "ranking_score": e.ranking_score,
            }
            for e in events[:20]
        ],
        "newsletter_mentions": newsletter_mentions[:30],
        "official_blogs": official_blogs[:10],
        "related_entities": related[:20],
    }
