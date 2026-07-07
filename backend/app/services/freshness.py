"""Knowledge freshness — staleness degrades confidence over time."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.article import CanonicalEvent

settings = get_settings()

STALENESS_DAYS_THRESHOLD = 21  # weeks without verification


def compute_staleness_score(
    last_verified_at: datetime | None,
    last_newsletter_seen: datetime | None,
    last_official_check: datetime | None,
) -> float:
    """0.0 = fresh, 1.0 = very stale."""
    now = datetime.now(timezone.utc)
    reference = last_verified_at or last_newsletter_seen or last_official_check
    if not reference:
        return 0.5

    days = (now - reference).days
    if days <= 3:
        return 0.0
    if days <= 7:
        return 0.15
    if days <= 14:
        return 0.35
    if days <= STALENESS_DAYS_THRESHOLD:
        return 0.55
    return min(0.5 + (days - STALENESS_DAYS_THRESHOLD) / 30, 1.0)


def apply_freshness_to_event(event: CanonicalEvent) -> None:
    """Update staleness and degrade confidence for stale events."""
    now = datetime.now(timezone.utc)

    if event.last_newsletter_seen is None and event.first_appearance_at:
        event.last_newsletter_seen = event.first_appearance_at

    event.staleness_score = compute_staleness_score(
        event.last_verified_at,
        event.last_newsletter_seen,
        event.last_official_check,
    )

    if event.staleness_score > 0.5 and event.confidence_score:
        degradation = event.staleness_score * 0.3
        event.confidence_score = max((event.confidence_score or 0) - degradation, 0.1)
        if event.staleness_score > 0.7:
            event.verification_level = "emerging"


async def touch_newsletter_seen(event: CanonicalEvent) -> None:
    event.last_newsletter_seen = datetime.now(timezone.utc)


async def touch_official_check(event: CanonicalEvent) -> None:
    event.last_official_check = datetime.now(timezone.utc)
    event.last_verified_at = datetime.now(timezone.utc)


async def refresh_stale_events(db: AsyncSession, user_id) -> int:
    """Periodic job: recompute staleness for all user events."""
    from sqlalchemy import select

    result = await db.execute(
        select(CanonicalEvent).where(CanonicalEvent.user_id == user_id)
    )
    events = list(result.scalars().all())
    for e in events:
        apply_freshness_to_event(e)
    await db.flush()
    return len(events)
