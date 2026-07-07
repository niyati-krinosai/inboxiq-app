"""Phase 19: Cross-newsletter comparison for the same canonical event."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import Article, CanonicalEvent, EventSource
from app.services.confidence import verification_label


async def get_event_comparison(db: AsyncSession, user_id: UUID, event_id: UUID) -> dict | None:
    result = await db.execute(
        select(CanonicalEvent)
        .where(CanonicalEvent.id == event_id, CanonicalEvent.user_id == user_id)
        .options(selectinload(CanonicalEvent.sources))
    )
    event = result.scalar_one_or_none()
    if not event:
        return None

    articles_result = await db.execute(
        select(Article).where(Article.canonical_event_id == event_id)
    )
    articles = {a.id: a for a in articles_result.scalars().all()}

    newsletter_coverage = []
    for source in (event.sources or []):
        article = articles.get(source.article_id)
        newsletter_coverage.append({
            "newsletter": source.newsletter_name,
            "source_type": source.source_type,
            "summary": source.full_summary or source.summary_snippet,
            "url": source.article_url,
            "perspective": _extract_perspective(article),
        })

    return {
        "event_id": str(event.id),
        "canonical_title": event.canonical_title or event.headline,
        "headline": event.headline,
        "ai_summary": {
            "primary": event.primary_summary,
            "why_it_matters": event.why_it_matters,
            "technical_impact": event.technical_impact,
            "business_impact": event.business_impact,
            "developer_impact": event.developer_impact,
        },
        "official_announcement": {
            "url": event.official_link,
            "enriched_excerpt": (event.enriched_content or "")[:2000],
        },
        "newsletter_coverage": newsletter_coverage,
        "verification": {
            "level": event.verification_level,
            "label": verification_label(event.verification_level),
            "confidence_score": event.confidence_score,
        },
        "technical_changes": event.technical_changes or [],
        "is_breaking": event.is_breaking,
        "is_trending": event.is_trending,
    }


def _extract_perspective(article: Article | None) -> str | None:
    if not article:
        return None
    return article.developer_takeaway or article.short_summary
