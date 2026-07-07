import json
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import CATEGORIES, TIMELINE_FILTERS
from app.core.logging import get_logger
from app.providers.openai_client import create_openai_client
from app.models.article import CanonicalEvent
from app.services.ask_over_time import is_longitudinal_question, synthesize_over_time
from app.services.chat_memory import build_memory_context, get_or_create_session, update_session_memory
from app.services.confidence import verification_label
from app.services.conflict_detection import format_conflicts_for_chat, get_open_conflicts_for_events
from app.services.explainability import build_explanation
from app.services.personalization import get_or_create_profile, personalization_boost, record_activity
from app.services.prompt_registry import get_production_prompt
from app.services.retrieval_metrics import log_retrieval
from app.services.reranker import extract_intent, rerank_events
from app.services.search import search_events, vector_search_events
from app.services.ai_extraction import generate_embedding

settings = get_settings()
log = get_logger(__name__)
client = create_openai_client()

CHAT_SYSTEM_PROMPT = """You are InboxIQ, a newsletter intelligence assistant.
You answer from CANONICAL EVENTS — merged, deduplicated intelligence from newsletters + official sources.
NEVER reference raw emails. NEVER search Gmail. NEVER invent facts.

Return JSON:
{
  "headline": "concise headline",
  "brief_summary": "2-3 sentences",
  "why_it_matters": "1-2 sentences",
  "technical_impact": "1-2 sentences",
  "business_impact": "1-2 sentences or null",
  "verification": "Verified|Highly Likely|Reported by newsletters|Emerging",
  "confidence_score": 0.0-1.0,
  "sources": [{"newsletter": "name", "url": "link or null"}],
  "official_link": "url or null",
  "related_news": ["headlines"],
  "is_breaking": false,
  "is_trending": false
}

Be concise and structured."""


def _infer_timeline(question: str) -> str:
    q = question.lower()
    for key, phrases in [
        ("24h", ("today", "24 hour")),
        ("2d", ("yesterday", "2 day")),
        ("4d", ("4 day",)),
        ("1w", ("this week", "past week", "last week")),
        ("2w", ("2 week",)),
        ("1m", ("this month", "past month")),
        ("2m", ("2 month",)),
    ]:
        if any(p in q for p in phrases):
            return key
    return "1w"


def _infer_categories(question: str) -> list[str]:
    q = question.lower()
    matched = [cat for cat in CATEGORIES if cat.lower() in q]
    keyword_map = {
        "funding": "Funding", "startup": "Startups", "api": "APIs",
        "model": "Models", "gpu": "GPU", "mcp": "MCP",
        "open source": "Open Source", "oss": "Open Source",
        "inference": "Inference", "server": "Servers",
        "langchain": "Developer Tools", "rag": "RAG",
        "vector": "Vector Databases", "agent": "Agentic AI",
    }
    for kw, cat in keyword_map.items():
        if kw in q and cat not in matched:
            matched.append(cat)
    return matched


def _build_context(events: list[CanonicalEvent]) -> str:
    items = []
    for e in events:
        sources = [{"newsletter": s.newsletter_name, "url": s.article_url} for s in (e.sources or [])]
        items.append({
            "canonical_title": e.canonical_title,
            "headline": e.headline,
            "summary": e.primary_summary,
            "why_it_matters": e.why_it_matters,
            "technical_impact": e.technical_impact,
            "technical_changes": e.technical_changes,
            "developer_impact": e.developer_impact,
            "business_impact": e.business_impact,
            "enriched_content": (e.enriched_content or "")[:1500],
            "categories": e.categories,
            "companies": e.companies,
            "official_link": e.official_link,
            "sources": sources,
            "verification": verification_label(e.verification_level),
            "confidence_score": e.confidence_score,
            "ranking_score": e.ranking_score,
            "is_breaking": e.is_breaking,
            "is_trending": e.is_trending,
            "newsletter_count": e.newsletter_count,
            "timeline": e.timeline_entries,
        })
    return json.dumps(items, indent=2)


async def _retrieve_events(
    db: AsyncSession,
    user_id,
    question: str,
    timeline: str,
    categories: list[str],
    intent: dict,
) -> list[CanonicalEvent]:
    all_events: list[CanonicalEvent] = []

    if settings.openai_api_key:
        embedding = await generate_embedding(question)
        if embedding:
            for cat in (categories or [None]):
                all_events.extend(await vector_search_events(
                    db, user_id, embedding, limit=15, timeline=timeline, category=cat,
                ))

    for cat in (categories or [None]):
        events, _ = await search_events(
            db, user_id, query=question, category=cat, timeline=timeline, limit=10, semantic=False
        )
        all_events.extend(events)

    if not categories:
        events, _ = await search_events(db, user_id, query=question, timeline=timeline, limit=10)
        all_events.extend(events)

    for entity in intent.get("entities", []):
        if entity.get("type") and entity.get("value"):
            events, _ = await search_events(
                db, user_id, entity_type=entity["type"], entity_value=entity["value"],
                timeline=timeline, limit=5, semantic=False,
            )
            all_events.extend(events)

    seen: set = set()
    unique = []
    for e in all_events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    profile = await get_or_create_profile(db, user_id)
    unique.sort(
        key=lambda e: (e.ranking_score or 0) + personalization_boost(e, profile) + (0.3 if e.is_breaking else 0),
        reverse=True,
    )
    return rerank_events(question, unique, top_k=8)


async def chat(
    db: AsyncSession,
    user_id,
    question: str,
    category_filter: str | None = None,
    timeline_filter: str | None = None,
    session_id: UUID | None = None,
) -> dict:
    """Event-centric chat with memory and Ask Over Time support."""
    t0 = time.perf_counter()
    session = await get_or_create_session(db, user_id, session_id)
    memory_ctx = build_memory_context(session)

    # Ask Over Time: longitudinal synthesis
    if is_longitudinal_question(question):
        result = await synthesize_over_time(db, user_id, question, timeline_filter)
        await record_activity(db, user_id, "question", {"question": question, "mode": "longitudinal"})
        await update_session_memory(db, session, question, result)
        return result

    intent = await extract_intent(question)
    timeline = timeline_filter or intent.get("timeline") or _infer_timeline(question)
    if timeline not in TIMELINE_FILTERS:
        timeline = "1w"

    categories = [category_filter] if category_filter else (intent.get("categories") or _infer_categories(question))

    # Use session memory to boost context
    if session.context_entities and not categories:
        for entity in session.context_entities[-3:]:
            events, _ = await search_events(db, user_id, query=entity, timeline=timeline, limit=5)
            if events:
                categories = categories or []

    ranked = await _retrieve_events(db, user_id, question, timeline, categories, intent)

    await record_activity(db, user_id, "question", {
        "question": question,
        "categories": categories,
        "topics": intent.get("entities", []),
    })

    if not ranked:
        return {
            "headline": "No matching intelligence found",
            "brief_summary": "No relevant canonical events in your knowledge base.",
            "why_it_matters": "Try broadening your query or wait for sync to complete.",
            "technical_impact": None,
            "business_impact": None,
            "verification": "Emerging",
            "confidence_score": 0,
            "sources": [],
            "official_link": None,
            "related_news": [],
            "session_id": str(session.id),
        }

    context = _build_context(ranked)
    conflicts = await get_open_conflicts_for_events(db, user_id, [e.id for e in ranked])
    conflict_lines = format_conflicts_for_chat(conflicts)
    if conflict_lines:
        context += "\n\nOpen conflicts:\n" + "\n".join(conflict_lines)

    user_msg = f"Memory:\n{memory_ctx}\n\nEvents:\n{context}\n\nQuestion: {question}"

    chat_prompt, _ = await get_production_prompt(db, "chat")
    system_prompt = chat_prompt or CHAT_SYSTEM_PROMPT

    if client:
        try:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            result = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:
            log.warning("chat_openai_failed", error=str(exc))
            top = ranked[0]
            sources = [{"newsletter": s.newsletter_name, "url": s.article_url} for s in (top.sources or [])]
            result = {
                "headline": top.headline,
                "brief_summary": top.primary_summary or "",
                "why_it_matters": top.why_it_matters or "",
                "technical_impact": top.technical_impact or "",
                "business_impact": top.business_impact,
                "verification": verification_label(top.verification_level),
                "confidence_score": top.confidence_score,
                "sources": sources,
                "official_link": top.official_link,
                "related_news": [e.headline for e in ranked[1:4]],
                "is_breaking": top.is_breaking,
                "is_trending": top.is_trending,
            }
    else:
        top = ranked[0]
        sources = [{"newsletter": s.newsletter_name, "url": s.article_url} for s in (top.sources or [])]
        result = {
            "headline": top.headline,
            "brief_summary": top.primary_summary or "",
            "why_it_matters": top.why_it_matters or "",
            "technical_impact": top.technical_impact or "",
            "business_impact": top.business_impact,
            "verification": verification_label(top.verification_level),
            "confidence_score": top.confidence_score,
            "sources": sources,
            "official_link": top.official_link,
            "related_news": [e.headline for e in ranked[1:4]],
            "is_breaking": top.is_breaking,
            "is_trending": top.is_trending,
        }

    result["session_id"] = str(session.id)
    result["explanation"] = build_explanation(
        question, ranked, categories, timeline,
        memory_entities=session.context_entities or [],
    ).to_dict()
    if conflicts:
        result["conflicts"] = [
            {"field": c.field, "claims": c.claims, "status": c.status}
            for c in conflicts if c.status == "open"
        ]

    await update_session_memory(
        db, session, question, result,
        retrieved_topics=categories,
        retrieved_entities=[e.headline for e in ranked[:3]],
    )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    await log_retrieval(
        db, user_id, question, "chat",
        retrieved_ids=[e.id for e in ranked],
        reranked_ids=[e.id for e in ranked],
        latency_ms=latency_ms,
    )
    return result
