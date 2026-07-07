"""Chat intent and query-driven retrieval tests."""

import pytest

from app.services.simple_chat import (
    _classify_intent,
    _extract_focus_query,
    _extract_story_subject,
    _query_tokens,
    _score_article,
)
from app.models.article import Article


def test_greeting_not_digest():
    assert _classify_intent("hi") == "greeting"
    assert _classify_intent("hello there") == "greeting"


def test_elaborate_intent():
    assert _classify_intent("elaborate on the OpenAI GPT release") == "elaborate"


def test_digest_intent():
    assert _classify_intent("summarize fintech news this week") == "digest"


def test_search_intent():
    assert _classify_intent("what did TLDR say about Claude agents") == "search"


def test_vague_short():
    assert _classify_intent("ok") == "vague"


def test_focus_extraction():
    assert "openai" in _extract_focus_query("elaborate on the OpenAI story").lower()


def test_weak_query_low_score():
    article = Article(
        title="Random unrelated topic",
        content_text="Something about cooking recipes.",
    )
    score = _score_article(article, "hi", _query_tokens("hi"), None, [], "search")
    assert score < 0.1


def test_specific_query_high_score():
    article = Article(
        title="OpenAI launches GPT-5",
        content_text="OpenAI announced GPT-5 with improved reasoning.",
    )
    q = "tell me about OpenAI GPT"
    score = _score_article(article, q, _query_tokens(q), None, [], "search")
    assert score > 0.3


def test_pasted_headline_extraction():
    q = "12. TESLA CAPS EMPLOYEE AI SPENDING AT $200/WEEK EXCEPT FOR GROK tell me more about this news"
    subject = _extract_story_subject(q)
    assert "tesla" in subject.lower()
    assert "grok" in subject.lower()
    assert "tell me more" not in subject.lower()


def test_tesla_story_scores_above_unrelated():
    tesla = Article(
        title="TESLA CAPS EMPLOYEE AI SPENDING AT $200/WEEK EXCEPT FOR GROK",
        content_text="Tesla limited internal AI tool spending to $200 per week except for Grok.",
    )
    other = Article(
        title="CLOUDED JUDGEMENT - THE END OF COMPUTE SCARCITY?",
        content_text="Meta and SpaceX selling compute capacity could mean excess supply.",
    )
    q = "12. TESLA CAPS EMPLOYEE AI SPENDING AT $200/WEEK EXCEPT FOR GROK tell me more about this news"
    focus = _extract_focus_query(q)
    tokens = _query_tokens(focus)
    tesla_score = _score_article(tesla, focus, tokens, "AI Startups", [], "elaborate")
    other_score = _score_article(other, focus, tokens, "AI Startups", [], "elaborate")
    assert tesla_score > other_score
    assert tesla_score >= 0.45
