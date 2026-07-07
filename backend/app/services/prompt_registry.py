"""Prompt registry — version, evaluate, rollback, A/B without code changes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_sourcing import PromptRegistry

DEFAULT_PROMPTS = {
    "extraction": """You extract structured knowledge from newsletter articles. Return only valid JSON.""",
    "chat": """You are InboxIQ. Answer from canonical events only. Return structured JSON.""",
    "canonicalize": """Merge newsletter articles into one canonical event. Return JSON only.""",
}


async def get_production_prompt(db: AsyncSession, name: str) -> tuple[str, str]:
    """Returns (content, version). Falls back to defaults."""
    result = await db.execute(
        select(PromptRegistry)
        .where(PromptRegistry.name == name, PromptRegistry.status == "production")
        .order_by(PromptRegistry.created_at.desc())
        .limit(1)
    )
    prompt = result.scalar_one_or_none()
    if prompt:
        return prompt.content, prompt.version
    return DEFAULT_PROMPTS.get(name, ""), "default"


async def register_prompt(
    db: AsyncSession,
    name: str,
    version: str,
    content: str,
    status: str = "draft",
    notes: str | None = None,
) -> PromptRegistry:
    prompt = PromptRegistry(
        name=name, version=version, content=content, status=status, notes=notes,
    )
    db.add(prompt)
    await db.flush()
    return prompt


async def promote_prompt(db: AsyncSession, name: str, version: str) -> PromptRegistry | None:
    """Promote a prompt version to production, archive previous."""
    result = await db.execute(
        select(PromptRegistry).where(PromptRegistry.name == name, PromptRegistry.version == version)
    )
    target = result.scalar_one_or_none()
    if not target:
        return None

    current = await db.execute(
        select(PromptRegistry).where(PromptRegistry.name == name, PromptRegistry.status == "production")
    )
    for p in current.scalars().all():
        p.status = "archived"

    target.status = "production"
    await db.flush()
    return target


async def rollback_prompt(db: AsyncSession, name: str) -> PromptRegistry | None:
    """Rollback to most recent archived production prompt."""
    result = await db.execute(
        select(PromptRegistry)
        .where(PromptRegistry.name == name, PromptRegistry.status == "archived")
        .order_by(PromptRegistry.created_at.desc())
        .limit(1)
    )
    prev = result.scalar_one_or_none()
    if not prev:
        return None
    return await promote_prompt(db, name, prev.version)


async def list_prompts(db: AsyncSession, name: str | None = None) -> list[dict]:
    stmt = select(PromptRegistry)
    if name:
        stmt = stmt.where(PromptRegistry.name == name)
    stmt = stmt.order_by(PromptRegistry.name, PromptRegistry.created_at.desc())
    result = await db.execute(stmt)
    return [
        {
            "name": p.name, "version": p.version, "status": p.status,
            "eval_score": p.eval_score, "created_at": p.created_at.isoformat(),
        }
        for p in result.scalars().all()
    ]
