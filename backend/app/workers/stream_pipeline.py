"""Streaming pipeline — independent stage workers via Celery chain."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.logging import get_logger
from app.database import AsyncSessionLocal
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.services.pipeline import clean_issue, process_segmented_pipeline, segment_issue
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


async def _load_issue(db, issue_id: str, user_id: str):
    result = await db.execute(
        select(Issue)
        .join(Newsletter)
        .where(Issue.id == uuid.UUID(issue_id), Newsletter.user_id == uuid.UUID(user_id))
        .options(selectinload(Issue.newsletter))
    )
    issue = result.scalar_one_or_none()
    if not issue:
        return None, None
    return issue, issue.newsletter


@celery_app.task(name="app.workers.stream.process_import")
def process_import_event(user_id: str, issue_id: str):
    process_clean_event.delay(user_id, issue_id)


@celery_app.task(name="app.workers.stream.process_clean")
def process_clean_event(user_id: str, issue_id: str):
    async def _run():
        async with AsyncSessionLocal() as db:
            issue, newsletter = await _load_issue(db, issue_id, user_id)
            if not issue:
                return
            await clean_issue(db, issue, uuid.UUID(user_id), newsletter.id)
            await db.commit()
        process_segment_event.delay(user_id, issue_id)

    _run_async(_run())


@celery_app.task(name="app.workers.stream.process_segment")
def process_segment_event(user_id: str, issue_id: str):
    async def _run():
        async with AsyncSessionLocal() as db:
            issue, newsletter = await _load_issue(db, issue_id, user_id)
            if not issue:
                return
            await segment_issue(db, issue, newsletter, uuid.UUID(user_id))
            await db.commit()
        process_extract_event.delay(user_id, issue_id)

    _run_async(_run())


@celery_app.task(name="app.workers.stream.process_extract")
def process_extract_event(user_id: str, issue_id: str):
    async def _run():
        async with AsyncSessionLocal() as db:
            issue, newsletter = await _load_issue(db, issue_id, user_id)
            if not issue:
                return
            await process_segmented_pipeline(db, issue, newsletter, uuid.UUID(user_id))
            await db.commit()

    _run_async(_run())


def enqueue_issue_pipeline(user_id: str, issue_id: str) -> None:
    """Entry point: publish import event to streaming pipeline."""
    process_import_event.delay(user_id, issue_id)
    log.info("pipeline_enqueued", user_id=user_id, issue_id=issue_id)
