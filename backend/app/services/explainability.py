"""Explain why a chat answer was generated — retrieval transparency."""

from dataclasses import dataclass, field

from app.models.article import CanonicalEvent


@dataclass
class RetrievalExplanation:
    matched_entities: list[str] = field(default_factory=list)
    matched_categories: list[str] = field(default_factory=list)
    timeline_filter: str | None = None
    confidence_threshold: float | None = None
    newsletter_mentions: int = 0
    retrieval_signals: list[str] = field(default_factory=list)
    events_used: list[str] = field(default_factory=list)
    memory_context: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "retrieved_because": self.retrieval_signals,
            "matched_entities": self.matched_entities,
            "matched_categories": self.matched_categories,
            "timeline": self.timeline_filter,
            "confidence_threshold": self.confidence_threshold,
            "newsletter_mentions": self.newsletter_mentions,
            "events_used": self.events_used,
            "memory_context": self.memory_context,
        }


def build_explanation(
    question: str,
    events: list[CanonicalEvent],
    categories: list[str],
    timeline: str,
    memory_entities: list[str] | None = None,
) -> RetrievalExplanation:
    exp = RetrievalExplanation(
        matched_categories=[c for c in categories if c],
        timeline_filter=timeline,
        memory_context=memory_entities or [],
    )

    q_lower = question.lower()

    for event in events[:5]:
        exp.events_used.append(event.canonical_title or event.headline)

        for company in (event.companies or []):
            if isinstance(company, str) and company.lower() in q_lower:
                exp.matched_entities.append(company)
                exp.retrieval_signals.append(f"✓ {company}")

        for cat in (event.categories or []):
            if cat in (categories or []):
                exp.retrieval_signals.append(f"✓ {cat}")

        if event.confidence_score and event.confidence_score >= 0.75:
            exp.retrieval_signals.append(f"✓ Confidence > {event.confidence_score:.1f}")

        nl_count = event.newsletter_count or len(event.sources or [])
        if nl_count >= 2:
            exp.newsletter_mentions = max(exp.newsletter_mentions, nl_count)
            exp.retrieval_signals.append(f"✓ Mentioned by {nl_count} newsletters")

    if timeline:
        exp.retrieval_signals.append(f"✓ Timeline: {timeline}")

    for entity in (memory_entities or []):
        if entity.lower() in q_lower:
            exp.retrieval_signals.append(f"✓ Memory context: {entity}")

    # Deduplicate signals
    exp.retrieval_signals = list(dict.fromkeys(exp.retrieval_signals))
    exp.matched_entities = list(dict.fromkeys(exp.matched_entities))

    return exp
