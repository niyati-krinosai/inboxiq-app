"""Pipeline dashboard — per-issue stage status."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.operations import PIPELINE_STAGES, PipelineStageTrace

STAGE_ORDER = [
    "discovery", "import", "clean", "segment",
    "extract", "embed", "deduplicate", "canonicalize", "enrich", "graph", "stored",
]


async def get_issue_pipeline_dashboard(
    db: AsyncSession,
    user_id: uuid.UUID,
    issue_id: uuid.UUID,
) -> dict | None:
    result = await db.execute(
        select(Issue)
        .join(Newsletter)
        .where(Issue.id == issue_id, Newsletter.user_id == user_id)
    )
    issue = result.scalar_one_or_none()
    if not issue:
        return None

    traces_result = await db.execute(
        select(PipelineStageTrace)
        .where(PipelineStageTrace.issue_id == issue_id)
        .order_by(PipelineStageTrace.started_at)
    )
    traces = list(traces_result.scalars().all())
    trace_by_stage = {t.stage: t for t in traces}

    stages = []
    for stage in STAGE_ORDER:
        t = trace_by_stage.get(stage)
        if t:
            stages.append({
                "stage": stage,
                "status": "✅" if t.status == "completed" else ("❌" if t.status == "failed" else "⏳"),
                "state": t.status,
                "duration_ms": t.duration_ms,
                "duration_s": round((t.duration_ms or 0) / 1000, 2),
                "tokens": {
                    "prompt": t.prompt_tokens,
                    "completion": t.completion_tokens,
                    "embedding": t.embedding_tokens,
                },
                "cost_usd": t.estimated_cost_usd,
                "failure_reason": t.failure_reason,
                "retry_count": t.retry_count,
                "model": t.model_name,
                "prompt_version": t.prompt_version,
            })
        elif stage in ("discovery", "import") and issue.processing_status != "imported":
            stages.append({"stage": stage, "status": "✅", "state": "completed", "duration_ms": None})

    total_duration = sum(s.get("duration_ms") or 0 for s in stages)
    total_cost = sum(s.get("cost_usd") or 0 for s in stages)

    return {
        "issue_id": str(issue.id),
        "subject": issue.subject,
        "processing_status": issue.processing_status,
        "error_message": issue.error_message,
        "retry_count": issue.retry_count,
        "stages": stages,
        "total_duration_ms": total_duration,
        "total_cost_usd": round(total_cost, 4),
    }


async def list_pipeline_statuses(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 20,
) -> list[dict]:
    result = await db.execute(
        select(Issue)
        .join(Newsletter)
        .where(Newsletter.user_id == user_id)
        .order_by(Issue.received_at.desc())
        .limit(limit)
    )
    issues = list(result.scalars().all())

    dashboards = []
    for issue in issues:
        dash = await get_issue_pipeline_dashboard(db, user_id, issue.id)
        if dash:
            dashboards.append({
                "issue_id": dash["issue_id"],
                "subject": dash["subject"],
                "processing_status": dash["processing_status"],
                "total_duration_ms": dash["total_duration_ms"],
                "total_cost_usd": dash["total_cost_usd"],
                "failed_stage": next(
                    (s["stage"] for s in dash["stages"] if s.get("state") == "failed"),
                    None,
                ),
            })
    return dashboards
