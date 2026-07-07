"""Phase 17: Personalized intelligence from user behavior."""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import CanonicalEvent
from app.models.intelligence import UserActivity, UserInterestProfile


async def get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> UserInterestProfile:
    result = await db.execute(
        select(UserInterestProfile).where(UserInterestProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        return profile
    profile = UserInterestProfile(
        user_id=user_id,
        category_weights={},
        topic_weights={},
        company_weights={},
        favorite_newsletter_ids=[],
    )
    db.add(profile)
    await db.flush()
    return profile


async def record_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    activity_type: str,
    payload: dict,
) -> None:
    db.add(UserActivity(user_id=user_id, activity_type=activity_type, payload=payload))
    await _update_profile_from_activity(db, user_id, activity_type, payload)
    await db.flush()


async def _update_profile_from_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    activity_type: str,
    payload: dict,
) -> None:
    profile = await get_or_create_profile(db, user_id)
    decay = 0.95
    learning_rate = 0.1

    cat_weights: dict[str, float] = dict(profile.category_weights or {})
    topic_weights: dict[str, float] = dict(profile.topic_weights or {})
    company_weights: dict[str, float] = dict(profile.company_weights or {})
    favorites: list = list(profile.favorite_newsletter_ids or [])

    # Decay all weights slightly
    for d in (cat_weights, topic_weights, company_weights):
        for k in d:
            d[k] *= decay

    if activity_type in ("click", "view_event", "question", "search"):
        for cat in payload.get("categories", []):
            cat_weights[cat] = cat_weights.get(cat, 0) + learning_rate
        for topic in payload.get("topics", []):
            topic_weights[topic] = topic_weights.get(topic, 0) + learning_rate
        for company in payload.get("companies", []):
            company_weights[company] = company_weights.get(company, 0) + learning_rate
        nl_id = payload.get("newsletter_id")
        if nl_id and nl_id not in favorites:
            favorites.append(nl_id)

    profile.category_weights = _normalize(cat_weights)
    profile.topic_weights = _normalize(topic_weights)
    profile.company_weights = _normalize(company_weights)
    profile.favorite_newsletter_ids = favorites[-20:]


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    if not weights:
        return {}
    total = sum(weights.values())
    if total == 0:
        return weights
    return {k: round(v / total, 4) for k, v in weights.items()}


def personalization_boost(event: CanonicalEvent, profile: UserInterestProfile | None) -> float:
    """Boost ranking_score based on user interest profile."""
    if not profile:
        return 0.0

    boost = 0.0
    cat_w = profile.category_weights or {}
    for cat in (event.categories or []):
        boost += cat_w.get(cat, 0) * 0.3

    co_w = profile.company_weights or {}
    for co in (event.companies or []):
        boost += co_w.get(co, 0) * 0.2

    topic_w = profile.topic_weights or {}
    for topic in (event.topics or []):
        boost += topic_w.get(topic, 0) * 0.15

    return min(boost, 0.4)


async def get_interest_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    profile = await get_or_create_profile(db, user_id)
    return {
        "categories": profile.category_weights or {},
        "topics": profile.topic_weights or {},
        "companies": profile.company_weights or {},
        "favorite_newsletters": profile.favorite_newsletter_ids or [],
    }
