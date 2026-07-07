"""Immutable event version log for canonical events."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import CanonicalEvent
from app.models.event_sourcing import CanonicalEventVersion


def _event_snapshot(event: CanonicalEvent) -> dict:
    return {
        "headline": event.headline,
        "canonical_title": event.canonical_title,
        "primary_summary": event.primary_summary,
        "why_it_matters": event.why_it_matters,
        "technical_impact": event.technical_impact,
        "business_impact": event.business_impact,
        "developer_impact": event.developer_impact,
        "technical_changes": event.technical_changes,
        "categories": event.categories,
        "companies": event.companies,
        "confidence_score": event.confidence_score,
        "verification_level": event.verification_level,
        "newsletter_count": event.newsletter_count,
        "official_link": event.official_link,
    }


async def record_event_version(
    db: AsyncSession,
    event: CanonicalEvent,
    change_type: str,
    change_reason: str | None = None,
    merged_source_ids: list | None = None,
    prompt_version: str | None = None,
    model_name: str | None = None,
) -> CanonicalEventVersion:
    result = await db.execute(
        select(func.max(CanonicalEventVersion.version)).where(
            CanonicalEventVersion.canonical_event_id == event.id
        )
    )
    max_ver = result.scalar() or 0

    version = CanonicalEventVersion(
        canonical_event_id=event.id,
        user_id=event.user_id,
        version=max_ver + 1,
        change_type=change_type,
        change_reason=change_reason,
        snapshot=_event_snapshot(event),
        merged_source_ids=merged_source_ids,
        prompt_version=prompt_version,
        model_name=model_name,
    )
    db.add(version)
    await db.flush()
    return version


async def get_event_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
) -> list[dict]:
    result = await db.execute(
        select(CanonicalEventVersion)
        .where(
            CanonicalEventVersion.canonical_event_id == event_id,
            CanonicalEventVersion.user_id == user_id,
        )
        .order_by(CanonicalEventVersion.version)
    )
    versions = list(result.scalars().all())
    return [
        {
            "version": v.version,
            "change_type": v.change_type,
            "change_reason": v.change_reason,
            "snapshot": v.snapshot,
            "merged_source_ids": v.merged_source_ids,
            "prompt_version": v.prompt_version,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


async def rebuild_event_at_version(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    version: int,
) -> dict | None:
    """Return snapshot at a specific version for audit/compare."""
    result = await db.execute(
        select(CanonicalEventVersion).where(
            CanonicalEventVersion.canonical_event_id == event_id,
            CanonicalEventVersion.user_id == user_id,
            CanonicalEventVersion.version == version,
        )
    )
    v = result.scalar_one_or_none()
    return v.snapshot if v else None
