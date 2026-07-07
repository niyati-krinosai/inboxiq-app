"""End-to-end pipeline stage tracing."""

import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.operations import PipelineStageTrace
from app.providers.base import LLMUsage
from app.services.llm_cost import estimate_cost, record_llm_usage

log = get_logger(__name__)


@asynccontextmanager
async def trace_stage(
    db: AsyncSession,
    user_id: uuid.UUID,
    stage: str,
    *,
    issue_id: uuid.UUID | None = None,
    newsletter_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
    retry_count: int = 0,
    model_name: str | None = None,
    prompt_version: str | None = None,
    provider: str | None = None,
):
    """Record start/end/duration/tokens/cost/failure for every pipeline stage."""
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    trace = PipelineStageTrace(
        user_id=user_id,
        issue_id=issue_id,
        newsletter_id=newsletter_id,
        article_id=article_id,
        stage=stage,
        status="running",
        started_at=started,
        retry_count=retry_count,
        model_name=model_name,
        prompt_version=prompt_version,
        provider=provider,
    )
    db.add(trace)
    await db.flush()

    usage_holder: dict = {"usage": LLMUsage()}

    class Tracer:
        def record_usage(self, usage: LLMUsage) -> None:
            usage_holder["usage"] = usage

    tracer = Tracer()

    try:
        yield tracer
        trace.status = "completed"
    except Exception as e:
        trace.status = "failed"
        trace.failure_reason = str(e)[:500]
        log.error("pipeline_stage_failed", stage=stage, issue_id=str(issue_id), error=str(e))
        raise
    finally:
        usage = usage_holder["usage"]
        trace.ended_at = datetime.now(timezone.utc)
        trace.duration_ms = int((time.perf_counter() - t0) * 1000)
        trace.prompt_tokens = usage.prompt_tokens
        trace.completion_tokens = usage.completion_tokens
        trace.embedding_tokens = usage.embedding_tokens
        trace.estimated_cost_usd = estimate_cost(usage)
        if usage.model:
            trace.model_name = usage.model
        if usage.provider:
            trace.provider = usage.provider
        await db.flush()

        if usage.prompt_tokens or usage.completion_tokens or usage.embedding_tokens:
            await record_llm_usage(db, user_id, stage, usage)

        log.info(
            "pipeline_stage_complete",
            stage=stage,
            status=trace.status,
            duration_ms=trace.duration_ms,
            cost_usd=trace.estimated_cost_usd,
            issue_id=str(issue_id) if issue_id else None,
        )
