"""LLM cost tracking — per user, per stage."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import LLMUsageLog, PipelineStageTrace
from app.providers.base import LLMUsage

# USD per 1M tokens (approximate, update as pricing changes)
COST_PER_MILLION = {
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "text-embedding-3-small": {"embedding": 0.02},
    "text-embedding-3-large": {"embedding": 0.13},
}


def estimate_cost(usage: LLMUsage) -> float:
    rates = COST_PER_MILLION.get(usage.model, {"prompt": 0.15, "completion": 0.60, "embedding": 0.02})
    cost = 0.0
    cost += (usage.prompt_tokens / 1_000_000) * rates.get("prompt", 0.15)
    cost += (usage.completion_tokens / 1_000_000) * rates.get("completion", 0.60)
    cost += (usage.embedding_tokens / 1_000_000) * rates.get("embedding", 0.02)
    return round(cost, 6)


async def record_llm_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    stage: str,
    usage: LLMUsage,
    model_version: dict | None = None,
) -> float:
    cost = estimate_cost(usage)
    db.add(LLMUsageLog(
        user_id=user_id,
        stage=stage,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        embedding_tokens=usage.embedding_tokens,
        estimated_cost_usd=cost,
        model_name=usage.model,
        provider=usage.provider,
        prompt_version=(model_version or {}).get("prompt_version"),
    ))
    return cost


async def get_user_cost_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(
            LLMUsageLog.stage,
            func.sum(LLMUsageLog.prompt_tokens).label("prompt_tokens"),
            func.sum(LLMUsageLog.completion_tokens).label("completion_tokens"),
            func.sum(LLMUsageLog.embedding_tokens).label("embedding_tokens"),
            func.sum(LLMUsageLog.estimated_cost_usd).label("cost"),
        )
        .where(LLMUsageLog.user_id == user_id)
        .group_by(LLMUsageLog.stage)
    )
    by_stage = [
        {
            "stage": row.stage,
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "embedding_tokens": row.embedding_tokens or 0,
            "estimated_cost_usd": round(row.cost or 0, 4),
        }
        for row in result.all()
    ]
    totals = {
        "prompt_tokens": sum(s["prompt_tokens"] for s in by_stage),
        "completion_tokens": sum(s["completion_tokens"] for s in by_stage),
        "embedding_tokens": sum(s["embedding_tokens"] for s in by_stage),
        "estimated_cost_usd": round(sum(s["estimated_cost_usd"] for s in by_stage), 4),
    }
    return {"by_stage": by_stage, "totals": totals}
