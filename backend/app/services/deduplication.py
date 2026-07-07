import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import get_logger
from app.models.article import Article, CanonicalEvent, EventSource
from app.services.event_canonicalization import canonicalize_event
from app.services.source_enrichment import enrich_article_sources

settings = get_settings()
log = get_logger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def _entity_overlap(a: Article, event: CanonicalEvent) -> float:
    """Phase 8: entity matching boost for deduplication."""
    score = 0.0
    pairs = [
        (a.companies, event.companies),
        (a.products, event.products),
        (a.frameworks, event.frameworks),
        (a.apis, event.apis),
        (a.models, event.models),
        (a.repositories, getattr(event, "repositories", None)),
    ]
    for a_vals, e_vals in pairs:
        if not a_vals or not e_vals:
            continue
        a_set = {v.lower() for v in a_vals if isinstance(v, str)}
        e_set = {v.lower() for v in e_vals if isinstance(v, str)}
        if a_set & e_set:
            score += 0.15
    return min(score, 0.45)


def _time_proximity_score(a: Article, event: CanonicalEvent) -> float:
    """Boost if published within dedup time window."""
    if not a.published_at or not event.published_at:
        return 0.0
    delta = abs((a.published_at - event.published_at).total_seconds()) / 3600
    if delta <= settings.dedup_time_window_hours:
        return 0.1 * (1 - delta / settings.dedup_time_window_hours)
    return 0.0


def _combined_score(embedding_score: float, entity_score: float, time_score: float) -> float:
    return embedding_score + entity_score + time_score


async def deduplicate_articles(
    db: AsyncSession,
    user_id: uuid.UUID,
    new_articles: list[Article],
    newsletter_names: dict[uuid.UUID, str] | None = None,
) -> list[CanonicalEvent]:
    """Phase 8: embedding similarity + entity matching + publication time."""
    if not new_articles:
        return []

    result = await db.execute(select(CanonicalEvent).where(CanonicalEvent.user_id == user_id))
    existing_events = list(result.scalars().all())
    created_events: list[CanonicalEvent] = []

    for article in new_articles:
        if article.canonical_event_id:
            continue

        best_event: CanonicalEvent | None = None
        best_score = 0.0
        embedding_score = 0.0

        if article.embedding is not None:
            for event in existing_events:
                if event.embedding is None:
                    continue
                emb = _cosine_similarity(article.embedding, event.embedding)
                entity = _entity_overlap(article, event)
                time_s = _time_proximity_score(article, event)
                combined = _combined_score(emb, entity, time_s)
                if combined > best_score:
                    best_score = combined
                    embedding_score = emb
                    best_event = event

        nl_name = (newsletter_names or {}).get(article.newsletter_id, "")

        if best_event and best_score >= settings.dedup_similarity_threshold:
            article.canonical_event_id = best_event.id
            _add_source(db, best_event, article, nl_name)
            await _merge_into_event(best_event, article, embedding_score)
            article.processing_status = "deduplicated"
        else:
            event = await _create_canonical_event(db, user_id, article)
            article.canonical_event_id = event.id
            _add_source(db, event, article, nl_name)
            article.processing_status = "deduplicated"
            existing_events.append(event)
            created_events.append(event)

    await db.flush()

    # Phase 16: canonicalize all touched events
    touched_ids = {a.canonical_event_id for a in new_articles if a.canonical_event_id}
    for event in existing_events:
        if event.id in touched_ids:
            await canonicalize_event(db, event)

    log.info("dedup_complete", articles=len(new_articles), new_events=len(created_events))
    return created_events


async def _merge_into_event(event: CanonicalEvent, article: Article, confidence: float) -> None:
    if article.short_summary and article.short_summary not in (event.alternative_explanations or []):
        alts = list(event.alternative_explanations or [])
        alts.append(article.short_summary)
        event.alternative_explanations = alts
    event.confidence = max(event.confidence or 0, confidence)

    # Merge enriched content from official sources
    if article.enriched_content and not event.enriched_content:
        event.enriched_content = article.enriched_content
        event.enriched_sources = article.enriched_sources

    if article.official_link and not event.official_link:
        event.official_link = article.official_link


async def _create_canonical_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    article: Article,
) -> CanonicalEvent:
    metadata = article.metadata_json or {}

    # Enrich canonical event from official sources at creation
    enriched, sources = await enrich_article_sources(
        article.official_link,
        metadata.get("supporting_sources"),
        article.content_text or "",
    )
    if enriched and not article.enriched_content:
        article.enriched_content = enriched
        article.enriched_sources = sources

    event = CanonicalEvent(
        user_id=user_id,
        headline=article.title,
        primary_summary=article.short_summary or metadata.get("summary"),
        why_it_matters=article.why_it_matters,
        technical_impact=article.technical_impact or article.impact,
        business_impact=article.business_impact,
        categories=article.categories,
        companies=article.companies,
        products=article.products,
        frameworks=article.frameworks,
        apis=article.apis,
        models=article.models,
        repositories=article.repositories,
        technologies=article.technologies,
        official_link=article.official_link,
        enriched_content=article.enriched_content,
        enriched_sources=article.enriched_sources,
        alternative_explanations=[],
        importance_score=article.importance_score,
        confidence=1.0,
        embedding=article.embedding,
        first_appearance_at=article.received_at,
        published_at=article.published_at,
        processed_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    await canonicalize_event(db, event)
    return event


def _add_source(
    db: AsyncSession,
    event: CanonicalEvent,
    article: Article,
    newsletter_name: str = "",
) -> None:
    db.add(EventSource(
        canonical_event_id=event.id,
        article_id=article.id,
        newsletter_id=article.newsletter_id,
        newsletter_name=newsletter_name,
        source_type="newsletter",
        source_weight=0.75,
        article_url=article.newsletter_link or article.url,
        summary_snippet=article.short_summary,
        full_summary=article.short_summary,
    ))
