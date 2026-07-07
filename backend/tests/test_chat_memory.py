"""Chat session memory and follow-up detection tests."""

from app.models.intelligence import ChatSession
from app.services.chat_memory import get_active_article, is_followup_question


def _session_with_active_article() -> ChatSession:
    return ChatSession(
        user_id="00000000-0000-0000-0000-000000000001",
        messages=[
            {"role": "user", "content": "Tell me about the X MCP story"},
            {
                "role": "assistant",
                "headline": "Deep dive",
                "content": "X launched MCP for the X API.",
                "active_article": {
                    "article_id": "11111111-1111-1111-1111-111111111111",
                    "title": "X HAS RELEASED A MODEL CONTEXT PROTOCOL",
                    "newsletter": "TLDR AI",
                },
            },
        ],
    )


def test_get_active_article_from_session():
    session = _session_with_active_article()
    active = get_active_article(session)
    assert active is not None
    assert "PROTOCOL" in active["title"].upper()


def test_followup_question_detected():
    session = _session_with_active_article()
    assert is_followup_question("Why is it not compatible with the Write API?", session) is True
    assert is_followup_question("so what makes it different from what already exist", session) is True
    assert is_followup_question("What about autonomous posting?", session) is True


def test_new_digest_not_followup():
    session = _session_with_active_article()
    assert is_followup_question("Summarize fintech news this week", session) is False
