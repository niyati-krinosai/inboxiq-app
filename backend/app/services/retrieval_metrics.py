"""Retrieval quality metrics."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import RetrievalMetric


async def log_retrieval(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    mode: str,
    retrieved_ids: list[uuid.UUID],
    reranked_ids: list[uuid.UUID],
    latency_ms: int,
    *,
    precision: float | None = None,
    recall: float | None = None,
    reranker_lift: float | None = None,
    hallucination_flagged: bool = False,
) -> RetrievalMetric:
    lift = 0.0
    if retrieved_ids and reranked_ids:
        if retrieved_ids[0] != reranked_ids[0]:
            lift = 1.0
        elif len(set(str(i) for i in retrieved_ids[:5]) ^ set(str(i) for i in reranked_ids[:5])) > 0:
            lift = 0.5

    metric = RetrievalMetric(
        user_id=user_id,
        query=query[:2000],
        mode=mode,
        events_retrieved=len(retrieved_ids),
        events_reranked=len(reranked_ids),
        top_event_ids=[str(i) for i in reranked_ids[:10]],
        precision_score=precision,
        recall_score=recall,
        reranker_lift=reranker_lift if reranker_lift is not None else lift,
        hallucination_flagged=hallucination_flagged,
        latency_ms=latency_ms,
    )
    db.add(metric)
    await db.flush()
    return metric


async def get_retrieval_metrics_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    all_metrics = list((await db.execute(
        select(RetrievalMetric).where(RetrievalMetric.user_id == user_id)
    )).scalars().all())

    by_mode: dict[str, dict] = {}
    for m in all_metrics:
        bucket = by_mode.setdefault(m.mode, {
            "count": 0, "avg_reranker_lift": 0.0, "avg_latency_ms": 0, "hallucination_count": 0,
        })
        bucket["count"] += 1
        bucket["avg_reranker_lift"] += m.reranker_lift or 0
        bucket["avg_latency_ms"] += m.latency_ms or 0
        if m.hallucination_flagged:
            bucket["hallucination_count"] += 1

    for bucket in by_mode.values():
        if bucket["count"]:
            bucket["avg_reranker_lift"] = round(bucket["avg_reranker_lift"] / bucket["count"], 3)
            bucket["avg_latency_ms"] = int(bucket["avg_latency_ms"] / bucket["count"])

    return {"by_mode": by_mode, "total_queries": len(all_metrics)}
