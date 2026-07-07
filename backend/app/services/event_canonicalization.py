"""Phase 16.1: Build rich canonical events from merged articles."""

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.logging import get_logger
from app.models.article import Article, CanonicalEvent, EventSource
from app.providers.openai_client import create_openai_client
from app.services.breaking_news import detect_breaking_trending
from app.services.confidence import compute_event_confidence
from app.services.conflict_detection import detect_and_store_conflicts
from app.services.event_sourcing import record_event_version
from app.services.freshness import apply_freshness_to_event, touch_newsletter_seen, touch_official_check
from app.services.importance_ranking import compute_ranking_score
from app.services.intelligence_graph import expand_event_graph

settings = get_settings()
log = get_logger(__name__)
client = create_openai_client()

CANONICALIZE_PROMPT = """You are building a canonical intelligence event from multiple newsletter articles about the SAME news.
Merge all perspectives into one authoritative event. Return JSON only:

{
  "canonical_title": "short canonical name e.g. GPT-6 Release",
  "headline": "best headline",
  "event_type": "launch|funding|api_release|acquisition|research|product_update|other",
  "primary_summary": "2-3 sentence unified summary",
  "why_it_matters": "1-2 sentences",
  "technical_impact": "1-2 sentences",
  "business_impact": "1-2 sentences or null",
  "developer_impact": "1-2 sentences",
  "technical_changes": ["list of specific technical changes mentioned"],
  "timeline_entries": [{"date": "ISO or descriptive", "milestone": "what happened"}],
  "companies": [], "products": [], "models": [], "apis": [], "frameworks": [],
  "technologies": [], "topics": [], "categories": []
}

Articles to merge:
"""


async def canonicalize_event(db: AsyncSession, event: CanonicalEvent) -> CanonicalEvent:
    """Merge all attached articles into a rich canonical event."""
    result = await db.execute(
        select(Article).where(Article.canonical_event_id == event.id)
    )
    articles = list(result.scalars().all())

    result = await db.execute(
        select(EventSource).where(EventSource.canonical_event_id == event.id)
    )
    sources = list(result.scalars().all())

    event.newsletter_count = len(sources)

    if not articles:
        return event

    # Build merge input from all article perspectives
    perspectives = []
    for a in articles:
        perspectives.append({
            "title": a.title,
            "summary": a.short_summary,
            "technical_impact": a.technical_impact,
            "business_impact": a.business_impact,
            "developer_takeaway": a.developer_takeaway,
            "companies": a.companies,
            "products": a.products,
            "official_link": a.official_link,
        })

    merged = await _llm_canonicalize(perspectives)
    _apply_canonical_fields(event, merged, articles)

    # Update source summaries for comparison feature
    for source in sources:
        article = next((a for a in articles if a.id == source.article_id), None)
        if article:
            source.full_summary = article.short_summary or (article.content_text or "")[:500]
            source.summary_snippet = article.short_summary
            if article.official_link and "github.com" in (article.official_link or ""):
                source.source_type = "github_release"
                source.source_weight = 0.95
            elif article.enriched_content:
                source.source_type = "official_blog"
                source.source_weight = 1.0
            else:
                source.source_type = "newsletter"
                source.source_weight = 0.75

    # Phase 16.2-16.4: confidence, breaking, ranking
    compute_event_confidence(event, sources)
    detect_breaking_trending(event, sources)
    event.ranking_score = compute_ranking_score(event)
    event.importance_score = event.ranking_score
    event.processed_at = datetime.now(timezone.utc)

    await touch_newsletter_seen(event)
    if event.official_link or event.enriched_content:
        await touch_official_check(event)
    apply_freshness_to_event(event)

    prev_version = event.current_version or 1
    change_type = "updated_summary"
    if prev_version <= 1 and len(sources) <= 1:
        change_type = "created"
    elif len(sources) > 1:
        change_type = "merged_sources"

    await detect_and_store_conflicts(db, event, articles)
    await record_event_version(
        db, event,
        change_type=change_type,
        change_reason=f"Canonicalized from {len(articles)} articles, {len(sources)} sources",
        merged_source_ids=[str(s.id) for s in sources],
        prompt_version=settings.canonicalize_prompt_version,
        model_name=settings.openai_model,
    )
    event.current_version = (event.current_version or 0) + 1

    await db.flush()
    await expand_event_graph(db, event.user_id, event)
    log.info("event_canonicalized", event_id=str(event.id), title=event.canonical_title)
    return event


async def canonicalize_events(db: AsyncSession, events: list[CanonicalEvent]) -> None:
    for event in events:
        await canonicalize_event(db, event)


async def _llm_canonicalize(perspectives: list[dict]) -> dict:
    if not client or len(perspectives) == 1:
        return _rule_based_merge(perspectives)

    content = CANONICALIZE_PROMPT + json.dumps(perspectives, indent=2)[:12000]
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "Merge newsletter articles into one canonical event. JSON only."},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        log.warning("canonicalize_event_failed", error=str(exc))
        return _rule_based_merge(perspectives)


def _rule_based_merge(perspectives: list[dict]) -> dict:
    p = perspectives[0] if perspectives else {}
    title = p.get("title", "Event")
    return {
        "canonical_title": title[:80],
        "headline": title,
        "event_type": "other",
        "primary_summary": p.get("summary", ""),
        "why_it_matters": p.get("summary", ""),
        "technical_impact": p.get("technical_impact"),
        "business_impact": p.get("business_impact"),
        "developer_impact": p.get("developer_takeaway"),
        "technical_changes": [],
        "timeline_entries": [],
        "companies": p.get("companies", []),
        "products": p.get("products", []),
        "models": [], "apis": [], "frameworks": [],
        "technologies": [], "topics": [], "categories": [],
    }


def _apply_canonical_fields(event: CanonicalEvent, merged: dict, articles: list[Article]) -> None:
    event.canonical_title = merged.get("canonical_title") or event.headline
    event.headline = merged.get("headline") or event.headline
    event.event_type = merged.get("event_type")
    event.primary_summary = merged.get("primary_summary") or event.primary_summary
    event.why_it_matters = merged.get("why_it_matters") or event.why_it_matters
    event.technical_impact = merged.get("technical_impact") or event.technical_impact
    event.business_impact = merged.get("business_impact") or event.business_impact
    event.developer_impact = merged.get("developer_impact")
    event.technical_changes = merged.get("technical_changes", [])

    # Build timeline from entries + article dates
    entries = merged.get("timeline_entries") or []
    for a in articles:
        if a.published_at:
            entries.append({
                "date": a.published_at.isoformat(),
                "milestone": f"Reported: {a.title[:80]}",
                "source": "newsletter",
            })
    event.timeline_entries = entries

    # Union entities from all articles
    for field in ("companies", "products", "models", "apis", "frameworks", "technologies", "topics", "categories"):
        merged_vals = set(merged.get(field) or [])
        for a in articles:
            for v in (getattr(a, field, None) or []):
                if isinstance(v, str):
                    merged_vals.add(v)
        setattr(event, field, list(merged_vals) if merged_vals else getattr(event, field, None))

    # Collect alternative explanations from each article
    alts = []
    for a in articles:
        if a.short_summary and a.short_summary not in alts:
            alts.append(a.short_summary)
    event.alternative_explanations = alts


def slugify_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120]
