"""User-controlled taxonomy — custom category collections."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import CanonicalEvent
from app.models.event_sourcing import UserTaxonomy


async def create_taxonomy(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    tags: list[str],
    description: str | None = None,
    entity_filters: dict | None = None,
) -> UserTaxonomy:
    taxonomy = UserTaxonomy(
        user_id=user_id,
        name=name,
        description=description,
        tags=tags,
        entity_filters=entity_filters,
    )
    db.add(taxonomy)
    await db.flush()
    return taxonomy


async def list_taxonomies(db: AsyncSession, user_id: uuid.UUID) -> list[UserTaxonomy]:
    result = await db.execute(
        select(UserTaxonomy).where(UserTaxonomy.user_id == user_id)
    )
    return list(result.scalars().all())


async def match_events_to_taxonomy(
    db: AsyncSession,
    user_id: uuid.UUID,
    taxonomy: UserTaxonomy,
    limit: int = 50,
) -> list[CanonicalEvent]:
    """Find events matching user's custom taxonomy tags."""
    result = await db.execute(
        select(CanonicalEvent).where(CanonicalEvent.user_id == user_id).limit(200)
    )
    events = list(result.scalars().all())
    tags = {t.lower() for t in (taxonomy.tags or [])}

    matched = []
    for e in events:
        searchable = " ".join([
            e.headline or "",
            e.canonical_title or "",
            e.primary_summary or "",
            " ".join(e.companies or []),
            " ".join(e.products or []),
            " ".join(e.technologies or []),
            " ".join(e.categories or []),
        ]).lower()
        if any(tag in searchable for tag in tags):
            matched.append(e)
        if len(matched) >= limit:
            break
    return matched
