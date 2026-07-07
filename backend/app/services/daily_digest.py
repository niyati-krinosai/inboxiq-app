"""Phase 24: Daily personalized digest generation."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.article import CanonicalEvent
from app.models.intelligence import DailyDigest
from app.providers.openai_client import create_openai_client
from app.services.personalization import get_or_create_profile, personalization_boost

settings = get_settings()
client = create_openai_client()


async def generate_daily_digest(db: AsyncSession, user_id: uuid.UUID) -> DailyDigest:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    # Check existing
    existing = await db.execute(
        select(DailyDigest).where(
            DailyDigest.user_id == user_id,
            DailyDigest.digest_date == today,
        )
    )
    digest = existing.scalar_one_or_none()
    if digest:
        return digest

    result = await db.execute(
        select(CanonicalEvent)
        .where(
            CanonicalEvent.user_id == user_id,
            CanonicalEvent.published_at >= yesterday,
        )
        .options(selectinload(CanonicalEvent.sources))
    )
    events = list(result.scalars().all())

    profile = await get_or_create_profile(db, user_id)
    events.sort(
        key=lambda e: (e.ranking_score or 0) + personalization_boost(e, profile),
        reverse=True,
    )
    top_events = events[:10]

    items = [
        {
            "headline": e.headline,
            "canonical_title": e.canonical_title,
            "summary": e.primary_summary,
            "why_it_matters": e.why_it_matters,
            "verification": e.verification_level,
            "is_breaking": e.is_breaking,
            "ranking_score": e.ranking_score,
            "categories": e.categories,
            "official_link": e.official_link,
            "sources": [s.newsletter_name for s in (e.sources or [])],
        }
        for e in top_events
    ]

    summary = await _generate_digest_summary(items, profile)

    digest = DailyDigest(
        user_id=user_id,
        digest_date=today,
        items=items,
        summary=summary,
    )
    db.add(digest)
    await db.flush()
    return digest


async def _generate_digest_summary(items: list[dict], profile) -> str:
    if not client or not items:
        cats = list((profile.category_weights or {}).keys())[:3]
        interest = ", ".join(cats) if cats else "your interests"
        return f"Top {len(items)} stories from your newsletters, personalized for {interest}."

    top_cats = list((profile.category_weights or {}).keys())[:5]
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": "Write a 5-minute morning digest summary. 3-4 paragraphs. Personalized tone.",
            },
            {
                "role": "user",
                "content": f"User interests: {top_cats}\n\nTop stories:\n{json.dumps(items, indent=2)[:8000]}",
            },
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content or ""


async def get_latest_digest(db: AsyncSession, user_id: uuid.UUID) -> DailyDigest | None:
    result = await db.execute(
        select(DailyDigest)
        .where(DailyDigest.user_id == user_id)
        .order_by(DailyDigest.digest_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
