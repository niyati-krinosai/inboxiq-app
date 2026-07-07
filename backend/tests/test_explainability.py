"""Unit tests for retrieval explainability."""

from app.services.explainability import build_explanation
from app.models.article import CanonicalEvent


def _event(title: str, companies=None, categories=None, confidence=0.92, nl_count=8):
    return CanonicalEvent(
        headline=title,
        canonical_title=title,
        companies=companies or [],
        categories=categories or [],
        confidence_score=confidence,
        newsletter_count=nl_count,
    )


def test_explanation_includes_entities():
    events = [_event("GPT-6 Released", companies=["OpenAI"])]
    exp = build_explanation("What did OpenAI announce?", events, ["Models"], "1w")
    d = exp.to_dict()
    assert any("OpenAI" in s for s in d["retrieved_because"])
    assert "GPT-6 Released" in d["events_used"]


def test_explanation_newsletter_mentions():
    events = [_event("Big Launch", nl_count=8)]
    exp = build_explanation("latest news", events, [], "1w")
    assert exp.newsletter_mentions >= 8
