"""Phase 18: Knowledge memory across chat turns."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import ChatSession


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


async def update_session_memory(
    db: AsyncSession,
    session: ChatSession,
    question: str,
    response: dict,
    retrieved_topics: list[str] | None = None,
    retrieved_entities: list[str] | None = None,
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

    # Extract entities from question (simple keyword pass)
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
