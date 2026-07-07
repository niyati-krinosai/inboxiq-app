"""Phase 23: AI Research Mode — comprehensive reports, not chat snippets."""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.providers.openai_client import create_openai_client
from app.services.ask_over_time import retrieve_events_for_topic
from app.services.company_intelligence import get_company_intelligence
from app.services.search import search_events, vector_search_events
from app.services.ai_extraction import generate_embedding

settings = get_settings()
client = create_openai_client()

RESEARCH_PROMPT = """You are an AI research assistant. Generate a comprehensive intelligence report.
Use ONLY the provided context from newsletters and official sources. Structure as JSON:

{
  "title": "report title",
  "executive_summary": "3-4 sentences",
  "key_findings": ["bullet points"],
  "timeline": [{"date": "...", "event": "..."}],
  "technical_analysis": "2-3 paragraphs",
  "business_implications": "1-2 paragraphs",
  "developer_implications": "1-2 paragraphs",
  "sources": [{"type": "newsletter|official|github|docs", "name": "...", "url": "..."}],
  "related_topics": ["..."],
  "confidence_assessment": "verified|highly_likely|reported|emerging"
}

Be thorough but factual. Never invent information."""


async def generate_research_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic: str,
    timeline: str = "2m",
) -> dict:
    """Deep research report: newsletters + official docs + GitHub + timeline."""
    all_events = await retrieve_events_for_topic(db, user_id, topic, timeline)

    if not all_events and settings.openai_api_key:
        embedding = await generate_embedding(topic)
        if embedding:
            all_events = await vector_search_events(
                db, user_id, embedding, limit=25, timeline=timeline
            )

    if not all_events:
        events, _ = await search_events(db, user_id, query=topic, timeline=timeline, limit=25)
        all_events = events

    if not all_events:
        return {
            "title": f"Research: {topic}",
            "executive_summary": "No intelligence found in your newsletter knowledge base for this topic.",
            "key_findings": [],
            "timeline": [],
            "sources": [],
        }

    context_items = []
    for e in all_events:
        context_items.append({
            "headline": e.headline,
            "canonical_title": e.canonical_title,
            "summary": e.primary_summary,
            "technical_impact": e.technical_impact,
            "developer_impact": e.developer_impact,
            "technical_changes": e.technical_changes,
            "enriched_content": (e.enriched_content or "")[:2000],
            "official_link": e.official_link,
            "verification": e.verification_level,
            "published_at": e.published_at.isoformat() if e.published_at else None,
            "sources": [
                {"newsletter": s.newsletter_name, "url": s.article_url}
                for s in (e.sources or [])
            ],
        })

    if client:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": RESEARCH_PROMPT},
                {
                    "role": "user",
                    "content": f"Topic: {topic}\n\nContext ({len(context_items)} events):\n{json.dumps(context_items, indent=2)[:14000]}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        report = json.loads(response.choices[0].message.content or "{}")
        report["event_count"] = len(all_events)
        report["topic"] = topic
        return report

    # Fallback without LLM
    return {
        "title": f"Research: {topic}",
        "executive_summary": all_events[0].primary_summary or "",
        "key_findings": [e.headline for e in all_events[:10]],
        "timeline": [
            {"date": e.published_at.isoformat() if e.published_at else None, "event": e.headline}
            for e in all_events
        ],
        "event_count": len(all_events),
        "topic": topic,
        "sources": [
            {"type": "newsletter", "name": s.newsletter_name, "url": s.article_url}
            for e in all_events[:5]
            for s in (e.sources or [])[:1]
        ],
    }
