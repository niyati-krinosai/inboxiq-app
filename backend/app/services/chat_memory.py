"""Phase 18: Knowledge memory across chat turns."""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import ChatSession

_NEW_TOPIC_PATTERNS = re.compile(
    r"\b(summarize|summary|digest|recap|roundup|everything|all stories|catch me up)\b",
    re.IGNORECASE,
)

_FOLLOWUP_PATTERNS = re.compile(
    r"\b("
    r"it|this|that|they|them|those|the story|this story|that story|the article|"
    r"the newsletter|the mcp|the api|about (it|this|that)|what about|how does|"
    r"why does|does it|can it|is it|are they|will it|would it"
    r")\b",
    re.IGNORECASE,
)


async def get_or_create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
) -> ChatSession:
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    session = ChatSession(
        user_id=user_id,
        context_topics=[],
        context_entities=[],
        messages=[],
    )
    db.add(session)
    await db.flush()
    return session


def get_active_article(session: ChatSession | None) -> dict | None:
    if not session or not session.messages:
        return None
    for msg in reversed(session.messages):
        if msg.get("role") == "assistant" and msg.get("active_article"):
            return msg["active_article"]
    return None


def get_conversation_turns(session: ChatSession | None) -> list[dict]:
    if not session or not session.messages:
        return []
    turns = []
    for msg in session.messages:
        role = msg.get("role")
        content = msg.get("content") or msg.get("headline")
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": str(content)})
    return turns


def should_answer_about_active_article(
    question: str,
    session: ChatSession | None,
    *,
    pinned_article_id: uuid.UUID | None = None,
) -> bool:
    if pinned_article_id:
        return True
    if not get_active_article(session):
        return False
    q = question.strip()
    if _NEW_TOPIC_PATTERNS.search(q):
        return False
    if len(q) >= 80 and re.search(r"\b(tell me|elaborate|detailed news)\b", q, re.I):
        return False
    return True


def is_followup_question(question: str, session: ChatSession | None) -> bool:
    return should_answer_about_active_article(question, session)


async def clear_active_article(db: AsyncSession, session: ChatSession) -> None:
    messages = list(session.messages or [])
    messages.append({
        "role": "assistant",
        "headline": "Article context cleared",
        "content": "",
        "active_article": None,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    session.messages = messages[-50:]
    await db.flush()


async def update_session_memory(
    db: AsyncSession,
    session: ChatSession,
    question: str,
    response: dict,
    retrieved_topics: list[str] | None = None,
    retrieved_entities: list[str] | None = None,
    active_article: dict | None = None,
) -> None:
    topics = list(session.context_topics or [])
    entities = list(session.context_entities or [])
    messages = list(session.messages or [])

    for t in (retrieved_topics or []):
        if t not in topics:
            topics.append(t)
    for e in (retrieved_entities or []):
        if e not in entities:
            entities.append(e)

    for word in question.split():
        if len(word) > 3 and word[0].isupper():
            if word not in entities:
                entities.append(word)

    messages.append({
        "role": "user",
        "content": question,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    messages.append({
        "role": "assistant",
        "headline": response.get("headline"),
        "content": _assistant_content(response),
        "active_article": active_article,
        "at": datetime.now(timezone.utc).isoformat(),
    })

    session.context_topics = topics[-20:]
    session.context_entities = entities[-30:]
    session.messages = messages[-50:]
    await db.flush()


def build_memory_context(session: ChatSession | None) -> str:
    if not session:
        return ""
    parts = []
    if session.context_entities:
        parts.append(f"Active entities: {', '.join(session.context_entities[-10:])}")
    if session.context_topics:
        parts.append(f"Active topics: {', '.join(session.context_topics[-10:])}")
    if session.messages:
        recent = session.messages[-6:]
        parts.append("Recent conversation:")
        for m in recent:
            role = m.get("role", "")
            content = m.get("content") or m.get("headline", "")
            parts.append(f"  {role}: {content[:200]}")
    return "\n".join(parts)


def _assistant_content(response: dict) -> str:
    items = response.get("items") or []
    if len(items) == 1 and items[0].get("summary"):
        return str(items[0]["summary"])
    return str(response.get("brief_summary") or response.get("headline") or "")
