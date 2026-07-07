import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.constants import TIMELINE_FILTERS
from app.models.article import Article, CanonicalEvent
from app.models.newsletter import Newsletter
from app.services.personalization import get_or_create_profile, personalization_boost
from app.services.ai_extraction import generate_embedding

settings = get_settings()


def _timeline_cutoff(filter_key: str | None) -> datetime | None:
    if not filter_key or filter_key not in TIMELINE_FILTERS:
        return None
    days = TIMELINE_FILTERS[filter_key]
    return datetime.now(timezone.utc) - timedelta(days=days)


async def vector_search_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    query_embedding: list[float],
    limit: int = 20,
    timeline: str | None = None,
    category: str | None = None,
) -> list[CanonicalEvent]:
    """Phase 12: semantic search via pgvector cosine distance."""
    cutoff = _timeline_cutoff(timeline)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    sql = """
        SELECT ce.id
        FROM canonical_events ce
        WHERE ce.user_id = :user_id
          AND ce.embedding IS NOT NULL
    """
    params: dict = {"user_id": str(user_id), "limit": limit, "embedding": embedding_str}

    if cutoff:
        sql += " AND ce.published_at >= :cutoff"
        params["cutoff"] = cutoff
    if category:
        sql += " AND ce.categories @> :category"
        params["category"] = f'["{category}"]'

    sql += " ORDER BY ce.embedding <=> :embedding::vector LIMIT :limit"

    result = await db.execute(text(sql), params)
    ids = [row[0] for row in result.all()]
    if not ids:
        return []

    events_result = await db.execute(
        select(CanonicalEvent)
        .where(CanonicalEvent.id.in_(ids))
        .options(selectinload(CanonicalEvent.sources))
    )
    events = list(events_result.scalars().all())
    id_order = {eid: i for i, eid in enumerate(ids)}
    events.sort(key=lambda e: id_order.get(e.id, 999))
    return events


async def search_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str | None = None,
    category: str | None = None,
    timeline: str | None = None,
    entity_type: str | None = None,
    entity_value: str | None = None,
    limit: int = 20,
    offset: int = 0,
    semantic: bool = True,
) -> tuple[list[CanonicalEvent], int]:
    """Phase 12: keyword + semantic + entity search."""
    # Semantic path
    if query and semantic and settings.openai_api_key:
        embedding = await generate_embedding(query)
        if embedding:
            vector_results = await vector_search_events(
                db, user_id, embedding, limit=limit, timeline=timeline, category=category
            )
            if vector_results:
                return vector_results, len(vector_results)

    stmt = (
        select(CanonicalEvent)
        .where(CanonicalEvent.user_id == user_id)
        .options(selectinload(CanonicalEvent.sources))
    )

    cutoff = _timeline_cutoff(timeline)
    if cutoff:
        stmt = stmt.where(CanonicalEvent.published_at >= cutoff)

    if category:
        stmt = stmt.where(CanonicalEvent.categories.contains([category]))

    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            or_(
                CanonicalEvent.headline.ilike(pattern),
                CanonicalEvent.primary_summary.ilike(pattern),
                CanonicalEvent.enriched_content.ilike(pattern),
                cast(CanonicalEvent.companies, String).ilike(pattern),
                cast(CanonicalEvent.products, String).ilike(pattern),
                cast(CanonicalEvent.frameworks, String).ilike(pattern),
                cast(CanonicalEvent.apis, String).ilike(pattern),
                cast(CanonicalEvent.models, String).ilike(pattern),
                cast(CanonicalEvent.repositories, String).ilike(pattern),
                cast(CanonicalEvent.technologies, String).ilike(pattern),
            )
        )

    entity_field_map = {
        "company": CanonicalEvent.companies,
        "product": CanonicalEvent.products,
        "framework": CanonicalEvent.frameworks,
        "api": CanonicalEvent.apis,
        "model": CanonicalEvent.models,
        "repository": CanonicalEvent.repositories,
        "person": None,
    }
    if entity_type and entity_value:
        field = entity_field_map.get(entity_type)
        if field is not None:
            stmt = stmt.where(cast(field, String).ilike(f"%{entity_value}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        stmt.order_by(
            CanonicalEvent.is_breaking.desc(),
            CanonicalEvent.ranking_score.desc().nullslast(),
            CanonicalEvent.importance_score.desc().nullslast(),
            CanonicalEvent.published_at.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_timeline_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    timeline: str = "1w",
    category: str | None = None,
    limit: int = 50,
    personalized: bool = True,
) -> list[CanonicalEvent]:
    events, _ = await search_events(
        db, user_id, timeline=timeline, category=category, limit=limit * 2, semantic=False
    )
    if personalized:
        profile = await get_or_create_profile(db, user_id)
        events.sort(
            key=lambda e: (e.ranking_score or 0) + personalization_boost(e, profile)
            + (0.3 if e.is_breaking else 0),
            reverse=True,
        )
    return events[:limit]


async def get_newsletters(db: AsyncSession, user_id: uuid.UUID) -> list[Newsletter]:
    result = await db.execute(
        select(Newsletter)
        .where(Newsletter.user_id == user_id)
        .order_by(Newsletter.issue_count.desc())
    )
    return list(result.scalars().all())


async def get_newsletter_detail(db: AsyncSession, newsletter_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    result = await db.execute(
        select(Newsletter).where(Newsletter.id == newsletter_id, Newsletter.user_id == user_id)
    )
    nl = result.scalar_one_or_none()
    if not nl:
        return None

    article_count = (await db.execute(
        select(func.count()).where(Article.newsletter_id == newsletter_id)
    )).scalar() or 0

    return {
        "id": nl.id,
        "name": nl.name,
        "sender_email": nl.sender_email,
        "domain": nl.domain,
        "frequency": nl.frequency,
        "issue_count": nl.issue_count,
        "article_count": article_count,
        "first_seen_at": nl.first_seen_at,
        "last_seen_at": nl.last_seen_at,
        "last_sync_at": nl.last_sync_at,
        "processing_status": nl.processing_status,
    }


async def get_newsletter_articles(
    db: AsyncSession,
    newsletter_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[Article]:
    result = await db.execute(
        select(Article)
        .where(Article.newsletter_id == newsletter_id, Article.user_id == user_id)
        .order_by(Article.received_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
