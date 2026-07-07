"""Phase 21: Hierarchical AI timeline (month → week → day → hour)."""

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import TIMELINE_FILTERS
from app.models.article import CanonicalEvent
from app.services.personalization import get_or_create_profile, personalization_boost


async def get_hierarchical_timeline(
    db: AsyncSession,
    user_id: uuid.UUID,
    timeline: str = "1m",
    category: str | None = None,
    personalized: bool = True,
) -> dict:
    cutoff_days = TIMELINE_FILTERS.get(timeline, 30)
    cutoff = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)

    stmt = (
        select(CanonicalEvent)
        .where(CanonicalEvent.user_id == user_id, CanonicalEvent.published_at >= cutoff)
        .options(selectinload(CanonicalEvent.sources))
    )
    if category:
        stmt = stmt.where(CanonicalEvent.categories.contains([category]))

    result = await db.execute(stmt)
    events = list(result.scalars().all())

    profile = await get_or_create_profile(db, user_id) if personalized else None

    def sort_key(e: CanonicalEvent) -> float:
        base = e.ranking_score or e.importance_score or 0
        if personalized and profile:
            base += personalization_boost(e, profile)
        if e.is_breaking:
            base += 0.3
        return base

    events.sort(key=sort_key, reverse=True)

    tree: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for e in events:
        dt = e.published_at or e.first_appearance_at or datetime.now(timezone.utc)
        month_key = dt.strftime("%Y-%m")
        week_key = f"W{dt.isocalendar()[1]:02d}"
        day_key = dt.strftime("%Y-%m-%d")
        hour_key = dt.strftime("%H:00")

        tree[month_key][week_key][day_key].append({
            "hour": hour_key,
            "event": _event_node(e),
        })

    # Restructure for API response
    months = []
    for month, weeks in sorted(tree.items(), reverse=True):
        week_list = []
        for week, days in sorted(weeks.items(), reverse=True):
            day_list = []
            for day, hour_events in sorted(days.items(), reverse=True):
                # Group by hour
                hours_map: dict[str, list] = defaultdict(list)
                for item in hour_events:
                    hours_map[item["hour"]].append(item["event"])
                day_list.append({
                    "date": day,
                    "hours": [
                        {"hour": h, "events": evts}
                        for h, evts in sorted(hours_map.items(), reverse=True)
                    ],
                })
            week_list.append({"week": week, "days": day_list})
        months.append({"month": month, "weeks": week_list})

    return {
        "timeline": timeline,
        "total_events": len(events),
        "months": months,
        "top_events": [_event_node(e) for e in events[:20]],
    }


def _event_node(e: CanonicalEvent) -> dict:
    return {
        "id": str(e.id),
        "headline": e.headline,
        "canonical_title": e.canonical_title,
        "summary": e.primary_summary,
        "ranking_score": e.ranking_score,
        "verification_level": e.verification_level,
        "is_breaking": e.is_breaking,
        "is_trending": e.is_trending,
        "newsletter_count": e.newsletter_count,
        "categories": e.categories,
        "companies": e.companies,
        "published_at": e.published_at.isoformat() if e.published_at else None,
        "sources": [
            {"newsletter": s.newsletter_name, "url": s.article_url}
            for s in (e.sources or [])
        ],
    }
