import asyncio
import uuid

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.logging import get_logger
from app.database import AsyncSessionLocal
from app.models.article import Article, CanonicalEvent, EventSource
from app.models.issue import Issue, PIPELINE_IMPORTED, PIPELINE_FAILED
from app.models.knowledge_graph import EntityRelation, KnowledgeEntity
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.daily_digest import generate_daily_digest
from app.services.freshness import refresh_stale_events
from app.services.gmail_sync import incremental_sync, initial_sync
from app.models.issue import PIPELINE_SEGMENTED
from app.services.pipeline import (
    get_imported_issues,
    process_issue_light,
    process_issue_pipeline,
    process_segmented_pipeline,
    run_light_pipeline_batch,
)
from app.workers.celery_app import celery_app

settings = get_settings()
log = get_logger(__name__)

_worker_loop = None


def _get_worker_loop():
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run_async(coro):
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


@celery_app.task(
    name="app.workers.tasks.sync_user_gmail",
    bind=True,
    max_retries=settings.celery_max_retries,
    default_retry_delay=settings.celery_retry_backoff,
)
def sync_user_gmail(self, user_id: str):
    async def _sync():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
            user = result.scalar_one_or_none()
            if not user or not user.gmail_connected:
                return {"error": "user not found or gmail disconnected"}

            try:
                if not user.initial_sync_complete:
                    sync_result = await initial_sync(db, user)
                else:
                    sync_result = await incremental_sync(db, user)
                await db.commit()
                run_intelligence_pipeline.delay(user_id)
                return sync_result
            except Exception as exc:
                user.sync_status = "failed"
                await db.commit()
                raise self.retry(exc=exc, countdown=settings.celery_retry_backoff * (2 ** self.request.retries))

    try:
        return _run_async(_sync())
    except MaxRetriesExceededError:
        log.error("sync_max_retries", user_id=user_id)
        return {"error": "max retries exceeded"}


@celery_app.task(
    name="app.workers.tasks.run_intelligence_pipeline",
    bind=True,
    max_retries=settings.celery_max_retries,
    default_retry_delay=settings.celery_retry_backoff,
)
def run_intelligence_pipeline(self, user_id: str):
    """Phases 4-9: clean → segment → extract → embed → dedup → enrich → graph."""
    async def _process():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
            user = result.scalar_one_or_none()
            if not user:
                return {"error": "user not found"}

            issues = await get_imported_issues(db, user.id, limit=settings.pipeline_batch_size)

            processed = 0
            failed = 0
            articles_total = 0

            for issue in issues:
                nl_result = await db.execute(
                    select(Newsletter).where(Newsletter.id == issue.newsletter_id)
                )
                newsletter = nl_result.scalar_one_or_none()
                if not newsletter:
                    continue

                if settings.use_streaming_pipeline:
                    from app.workers.stream_pipeline import enqueue_issue_pipeline
                    enqueue_issue_pipeline(user_id, str(issue.id))
                    processed += 1
                    continue

                try:
                    if settings.simple_mode:
                        articles = await process_issue_light(db, issue, newsletter, user.id)
                    elif issue.processing_status == PIPELINE_SEGMENTED:
                        articles = await process_segmented_pipeline(db, issue, newsletter, user.id)
                    else:
                        articles = await process_issue_pipeline(db, issue, newsletter, user.id)
                    processed += 1
                    articles_total += len(articles)
                except Exception as e:
                    failed += 1
                    log.warning("issue_pipeline_failed", issue_id=str(issue.id), error=str(e))

            await db.commit()

            # Chain if more issues remain
            remaining = await get_imported_issues(db, user.id, limit=1)
            if remaining:
                run_intelligence_pipeline.delay(user_id)

            return {"processed": processed, "failed": failed, "articles": articles_total}

    try:
        return _run_async(_process())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=settings.celery_retry_backoff * (2 ** self.request.retries))


@celery_app.task(name="app.workers.tasks.sync_all_users")
def sync_all_users():
    """Phase 14: hourly sync for all connected users."""
    async def _sync_all():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.gmail_connected == True)  # noqa: E712
            )
            users = list(result.scalars().all())
            for user in users:
                sync_user_gmail.delay(str(user.id))
            log.info("scheduled_sync_all", users=len(users))
            return {"users": len(users)}

    return _run_async(_sync_all())


@celery_app.task(name="app.workers.tasks.generate_all_digests")
def generate_all_digests():
    """Phase 24: generate daily digests for all users."""
    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User))
            users = list(result.scalars().all())
            for user in users:
                try:
                    await generate_daily_digest(db, user.id)
                except Exception as e:
                    log.warning("digest_failed", user_id=str(user.id), error=str(e))
            await db.commit()
            return {"users": len(users)}

    return _run_async(_run())


@celery_app.task(name="app.workers.tasks.refresh_all_freshness")
def refresh_all_freshness():
    """Recompute staleness scores for all users."""
    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User))
            users = list(result.scalars().all())
            total = 0
            for user in users:
                total += await refresh_stale_events(db, user.id)
            await db.commit()
            return {"users": len(users), "events_refreshed": total}

    return _run_async(_run())
