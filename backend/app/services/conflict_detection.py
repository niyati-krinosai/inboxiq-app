"""Detect and store conflicting claims across newsletter sources."""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article, CanonicalEvent
from app.models.event_sourcing import EventConflict


FUNDING_PATTERN = re.compile(r"\$[\d,.]+\s*[MBmb]?(?:illion)?|\d+\s*million", re.IGNORECASE)


def _extract_funding_claims(articles: list[Article]) -> list[dict]:
    claims = []
    for a in articles:
        text = f"{a.title} {a.content_text or ''} {a.short_summary or ''}"
        for match in FUNDING_PATTERN.findall(text):
            claims.append({
                "field": "funding_amount",
                "value": match.strip(),
                "source": a.newsletter_link or a.url,
                "article_id": str(a.id),
                "title": a.title,
            })
    return claims


def _find_conflicts(claims: list[dict]) -> list[dict]:
    """Group claims with different values for same field."""
    by_field: dict[str, set[str]] = {}
    claim_map: dict[str, list[dict]] = {}

    for c in claims:
        field = c["field"]
        val = c["value"].lower().replace(",", "").replace(" ", "")
        by_field.setdefault(field, set()).add(val)
        claim_map.setdefault(f"{field}:{val}", []).append(c)

    conflicts = []
    for field, values in by_field.items():
        if len(values) > 1:
            all_claims = []
            for v in values:
                all_claims.extend(claim_map.get(f"{field}:{v}", []))
            conflicts.append({"field": field, "claims": all_claims})
    return conflicts


async def detect_and_store_conflicts(
    db: AsyncSession,
    event: CanonicalEvent,
    articles: list[Article],
) -> list[EventConflict]:
    funding_claims = _extract_funding_claims(articles)
    conflict_groups = _find_conflicts(funding_claims)
    stored: list[EventConflict] = []

    for group in conflict_groups:
        existing = await db.execute(
            select(EventConflict).where(
                EventConflict.canonical_event_id == event.id,
                EventConflict.field == group["field"],
                EventConflict.status == "open",
            )
        )
        if existing.scalar_one_or_none():
            continue

        conflict = EventConflict(
            canonical_event_id=event.id,
            user_id=event.user_id,
            field=group["field"],
            claims=group["claims"],
            status="open",
        )
        db.add(conflict)
        stored.append(conflict)

    await db.flush()
    return stored


async def resolve_conflict(
    db: AsyncSession,
    conflict_id: uuid.UUID,
    user_id: uuid.UUID,
    resolved_value: str,
    resolution: str,
    resolved_source: str = "manual",
) -> EventConflict | None:
    result = await db.execute(
        select(EventConflict).where(
            EventConflict.id == conflict_id,
            EventConflict.user_id == user_id,
        )
    )
    conflict = result.scalar_one_or_none()
    if not conflict:
        return None

    conflict.resolved_value = resolved_value
    conflict.resolution = resolution
    conflict.resolved_source = resolved_source
    conflict.status = "resolved"
    conflict.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return conflict


async def get_open_conflicts_for_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_ids: list[uuid.UUID],
) -> list[EventConflict]:
    if not event_ids:
        return []
    result = await db.execute(
        select(EventConflict).where(
            EventConflict.user_id == user_id,
            EventConflict.canonical_event_id.in_(event_ids),
            EventConflict.status == "open",
        )
    )
    return list(result.scalars().all())


async def list_event_conflicts(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID | None = None,
) -> list[EventConflict]:
    stmt = select(EventConflict).where(EventConflict.user_id == user_id)
    if event_id:
        stmt = stmt.where(EventConflict.canonical_event_id == event_id)
    result = await db.execute(stmt.order_by(EventConflict.created_at.desc()))
    return list(result.scalars().all())


def format_conflicts_for_chat(conflicts: list[EventConflict]) -> list[str]:
    lines = []
    for c in conflicts:
        if c.status != "open":
            continue
        values = list({cl.get("value") for cl in (c.claims or [])})
        if len(values) >= 2:
            lines.append(
                f"Conflicting {c.field}: {values[0]} vs {values[1]} "
                f"(from {len(c.claims or [])} sources)"
            )
    return lines
