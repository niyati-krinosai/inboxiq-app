"""Phases 16-25: Intelligence quality APIs."""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.ai_timeline import get_hierarchical_timeline
from app.services.analytics import get_analytics
from app.services.ask_over_time import synthesize_over_time
from app.services.company_intelligence import get_company_intelligence
from app.services.comparison import get_event_comparison
from app.services.confidence import verification_label
from app.services.daily_digest import generate_daily_digest, get_latest_digest
from app.services.intelligence_graph import get_event_graph
from app.services.personalization import get_interest_summary, record_activity
from app.services.research_mode import generate_research_report

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


class ResearchRequest(BaseModel):
    topic: str
    timeline: str = "2m"


class AskOverTimeRequest(BaseModel):
    question: str
    timeline: str | None = None


class ActivityRequest(BaseModel):
    activity_type: str  # click|view_event|search
    payload: dict = {}


@router.get("/events/{event_id}")
async def get_canonical_event(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 16: Full canonical event with all merged intelligence."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.article import CanonicalEvent

    result = await db.execute(
        select(CanonicalEvent)
        .where(CanonicalEvent.id == event_id, CanonicalEvent.user_id == user.id)
        .options(selectinload(CanonicalEvent.sources))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "id": str(event.id),
        "canonical_title": event.canonical_title,
        "headline": event.headline,
        "event_type": event.event_type,
        "primary_summary": event.primary_summary,
        "why_it_matters": event.why_it_matters,
        "technical_impact": event.technical_impact,
        "business_impact": event.business_impact,
        "developer_impact": event.developer_impact,
        "technical_changes": event.technical_changes,
        "timeline_entries": event.timeline_entries,
        "official_link": event.official_link,
        "enriched_content": (event.enriched_content or "")[:3000],
        "verification": {
            "level": event.verification_level,
            "label": verification_label(event.verification_level),
            "confidence_score": event.confidence_score,
        },
        "ranking_score": event.ranking_score,
        "importance_factors": event.importance_factors,
        "is_breaking": event.is_breaking,
        "is_trending": event.is_trending,
        "newsletter_count": event.newsletter_count,
        "current_version": event.current_version,
        "freshness": {
            "last_verified_at": event.last_verified_at.isoformat() if event.last_verified_at else None,
            "last_newsletter_seen": event.last_newsletter_seen.isoformat() if event.last_newsletter_seen else None,
            "last_official_check": event.last_official_check.isoformat() if event.last_official_check else None,
            "staleness_score": event.staleness_score,
        },
        "categories": event.categories,
        "companies": event.companies,
        "sources": [
            {
                "newsletter": s.newsletter_name,
                "type": s.source_type,
                "weight": s.source_weight,
                "summary": s.full_summary or s.summary_snippet,
                "url": s.article_url,
            }
            for s in (event.sources or [])
        ],
    }


@router.get("/events/{event_id}/comparison")
async def event_comparison(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 19: Cross-newsletter comparison."""
    result = await get_event_comparison(db, user.id, event_id)
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")
    return result


@router.get("/events/{event_id}/graph")
async def event_graph(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 25: Event-centric intelligence graph."""
    return await get_event_graph(db, user.id, event_id)


@router.get("/timeline/hierarchical")
async def hierarchical_timeline(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    filter: str = Query("1m", alias="filter"),
    category: str | None = None,
    personalized: bool = True,
):
    """Phase 21: Month → Week → Day → Hour timeline."""
    return await get_hierarchical_timeline(db, user.id, filter, category, personalized)


@router.get("/companies/{company_name}")
async def company_page(
    company_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 22: Company intelligence page."""
    return await get_company_intelligence(db, user.id, company_name)


@router.post("/research")
async def research_mode(
    body: ResearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 23: AI research report generation."""
    return await generate_research_report(db, user.id, body.topic, body.timeline)


@router.post("/ask-over-time")
async def ask_over_time(
    body: AskOverTimeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Longitudinal synthesis across a time window."""
    return await synthesize_over_time(db, user.id, body.question, body.timeline)


@router.get("/digest")
async def daily_digest(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    generate: bool = False,
):
    """Phase 24: Daily personalized digest."""
    if generate:
        digest = await generate_daily_digest(db, user.id)
        await db.commit()
    else:
        digest = await get_latest_digest(db, user.id)
        if not digest:
            digest = await generate_daily_digest(db, user.id)
            await db.commit()

    return {
        "date": digest.digest_date.isoformat(),
        "summary": digest.summary,
        "items": digest.items,
    }


@router.get("/analytics")
async def newsletter_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 20: Newsletter analytics dashboard."""
    return await get_analytics(db, user.id)


@router.get("/profile")
async def interest_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 17: User interest profile."""
    return await get_interest_summary(db, user.id)


@router.post("/activity")
async def track_activity(
    body: ActivityRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 17: Record user activity for personalization."""
    await record_activity(db, user.id, body.activity_type, body.payload)
    await db.commit()
    return {"status": "recorded"}
