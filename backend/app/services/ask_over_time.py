"""Ask Over Time + longitudinal event retrieval."""

import json
import re
from datetime import datetime, timezone

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.logging import get_logger
from app.constants import TIMELINE_FILTERS
from app.models.article import CanonicalEvent
from app.providers.openai_client import create_openai_client
from app.services.ai_extraction import generate_embedding
from app.services.search import vector_search_events

settings = get_settings()
log = get_logger(__name__)

# Patterns indicating longitudinal / evolution questions
LONGITUDINAL_PATTERNS = [
    r"how has .+ evolved",
    r"how did .+ change",
    r"over the (?:last|past)",
    r"since \w+",
    r"every announcement",
    r"show .+ over",
    r"compare .+ over",
    r"history of",
    r"timeline of",
    r"progression of",
    r"track .+ over",
]


def is_longitudinal_question(question: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in LONGITUDINAL_PATTERNS)


def extract_topic_from_question(question: str) -> str:
    """Extract primary topic entity from a longitudinal question."""
    q = question.lower()
    # Remove common question framing
    for phrase in ("how has", "how did", "tell me everything about", "show me", "what is", "explain"):
        q = q.replace(phrase, "")
    for phrase in ("evolved over", "changed over", "over the last", "over the past", "since"):
        idx = q.find(phrase)
        if idx > 0:
            q = q[:idx]
    q = re.sub(r"\b(the|a|an|in|ai|this week|this month|two months|six weeks)\b", "", q)
    return q.strip().title() or question.strip()


def infer_extended_timeline(question: str) -> str:
    q = question.lower()
    if "six week" in q or "2 month" in q or "two month" in q:
        return "2m"
    if "month" in q:
        return "1m"
    if "week" in q:
        return "2w"
    return "2m"


async def retrieve_events_for_topic(
    db: AsyncSession,
    user_id,
    topic: str,
    timeline: str = "2m",
) -> list[CanonicalEvent]:
    """Retrieve and chronologically order all events related to a topic."""
    from datetime import timedelta

    cutoff_days = TIMELINE_FILTERS.get(timeline, 60)
    cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
    pattern = f"%{topic}%"

    stmt = (
        select(CanonicalEvent)
        .where(
            CanonicalEvent.user_id == user_id,
            CanonicalEvent.published_at >= cutoff,
            or_(
                CanonicalEvent.headline.ilike(pattern),
                CanonicalEvent.canonical_title.ilike(pattern),
                CanonicalEvent.primary_summary.ilike(pattern),
                cast(CanonicalEvent.companies, String).ilike(pattern),
                cast(CanonicalEvent.products, String).ilike(pattern),
                cast(CanonicalEvent.topics, String).ilike(pattern),
                cast(CanonicalEvent.technologies, String).ilike(pattern),
                CanonicalEvent.enriched_content.ilike(pattern),
            ),
        )
        .options(selectinload(CanonicalEvent.sources))
    )

    result = await db.execute(stmt)
    events = list(result.scalars().all())

    # Supplement with vector search
    embedding = await generate_embedding(topic)
    if embedding:
        vector_events = await vector_search_events(
            db, user_id, embedding, limit=20, timeline=timeline
        )
        seen = {e.id for e in events}
        for e in vector_events:
            if e.id not in seen:
                events.append(e)

    # Chronological order for longitudinal synthesis
    events.sort(key=lambda e: e.published_at or e.first_appearance_at or datetime.min.replace(tzinfo=timezone.utc))
    return events


async def synthesize_over_time(
    db: AsyncSession,
    user_id,
    question: str,
    timeline: str | None = None,
) -> dict:
    """Ask Over Time: retrieve, order, and synthesize events across a time window."""
    topic = extract_topic_from_question(question)
    tl = timeline or infer_extended_timeline(question)
    events = await retrieve_events_for_topic(db, user_id, topic, tl)

    if not events:
        return {
            "headline": f"No timeline found for: {topic}",
            "brief_summary": "No events in your knowledge base match this longitudinal query.",
            "timeline_synthesis": [],
            "evolution_summary": None,
            "sources": [],
            "official_link": None,
            "related_news": [],
        }

    timeline_synthesis = []
    for e in events:
        timeline_synthesis.append({
            "date": e.published_at.isoformat() if e.published_at else None,
            "headline": e.headline,
            "canonical_title": e.canonical_title,
            "summary": e.primary_summary,
            "technical_changes": e.technical_changes,
            "verification": e.verification_level,
            "newsletter_count": e.newsletter_count,
            "sources": [s.newsletter_name for s in (e.sources or [])],
        })

    settings = get_settings()
    oai = create_openai_client()

    if oai:
        try:
            response = await oai.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Synthesize how a topic evolved over time from chronological events. "
                            "Return JSON: {headline, brief_summary, evolution_summary (2-3 paragraphs), "
                            "key_milestones: [{date, milestone}], why_it_matters, technical_impact, "
                            "sources: [{newsletter, url}], official_link, related_news: []}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nChronological events:\n{json.dumps(timeline_synthesis, indent=2)[:12000]}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            result = json.loads(response.choices[0].message.content or "{}")
            result["timeline_synthesis"] = timeline_synthesis
            result["topic"] = topic
            result["event_count"] = len(events)
            return result
        except Exception as exc:
            log.warning("synthesize_over_time_failed", error=str(exc))

    return {
        "headline": f"Timeline: {topic}",
        "brief_summary": f"Found {len(events)} events related to {topic} over {tl}.",
        "evolution_summary": None,
        "timeline_synthesis": timeline_synthesis,
        "topic": topic,
        "event_count": len(events),
        "sources": [
            {"newsletter": s.newsletter_name, "url": s.article_url}
            for e in events[-1:]
            for s in (e.sources or [])
        ],
        "official_link": events[-1].official_link if events else None,
        "related_news": [e.headline for e in events[-4:-1]],
    }
