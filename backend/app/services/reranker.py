import json
from datetime import datetime, timezone

from app.config import get_settings
from app.core.logging import get_logger
from app.models.article import CanonicalEvent
from app.providers.openai_client import create_openai_client

settings = get_settings()
log = get_logger(__name__)
client = create_openai_client()

_DEFAULT_INTENT = {"categories": [], "timeline": "1w", "entities": [], "intent": "search"}


async def extract_intent(question: str) -> dict:
    """Phase 11: extract intent, categories, and timeline from question."""
    if not client:
        return dict(_DEFAULT_INTENT)

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract search intent from the user question. Return JSON: "
                        '{"categories": [], "timeline": "24h|2d|4d|1w|2w|1m|2m", '
                        '"entities": [{"type": "company|product|api|framework|model", "value": "..."}], '
                        '"intent": "summary|search|comparison|timeline"}'
                    ),
                },
                {"role": "user", "content": question},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        log.warning("extract_intent_failed", error=str(exc))
        return dict(_DEFAULT_INTENT)


def rerank_events(question: str, events: list[CanonicalEvent], top_k: int = 8) -> list[CanonicalEvent]:
    """Phase 11: lightweight reranker using keyword overlap + importance."""
    if not events:
        return []

    q_tokens = set(question.lower().split())

    def score(event: CanonicalEvent) -> float:
        text = f"{event.headline} {event.primary_summary or ''} {event.enriched_content or ''}".lower()
        overlap = sum(1 for t in q_tokens if len(t) > 3 and t in text) / max(len(q_tokens), 1)
        importance = event.importance_score or 0.5
        recency = 0.0
        if event.published_at:
            age_days = (datetime.now(timezone.utc) - event.published_at).days
            recency = max(0, 1 - age_days / 30)
        return overlap * 0.5 + importance * 0.35 + recency * 0.15

    ranked = sorted(events, key=score, reverse=True)
    return ranked[:top_k]
