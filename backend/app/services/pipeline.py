from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.pipeline_tracer import trace_stage
from app.models.article import Article
from app.models.issue import (
    PIPELINE_CLEANED,
    PIPELINE_COMPLETED,
    PIPELINE_EXTRACTING,
    PIPELINE_FAILED,
    PIPELINE_IMPORTED,
    PIPELINE_SEGMENTED,
    Issue,
)
from app.models.newsletter import Newsletter
from app.config import get_settings
from app.services.ai_extraction import extract_and_embed_article
from app.services.article_segmentation import segment_from_html
from app.services.deduplication import deduplicate_articles
from app.services.html_cleaner import clean_newsletter_html

settings = get_settings()
log = get_logger(__name__)


async def clean_issue(db: AsyncSession, issue: Issue, user_id, newsletter_id) -> None:
    async with trace_stage(
        db, user_id, "clean",
        issue_id=issue.id, newsletter_id=newsletter_id,
        retry_count=issue.retry_count or 0,
    ):
        cleaned = clean_newsletter_html(issue.raw_html or "")
        issue.cleaned_text = cleaned.text
        issue.processing_status = PIPELINE_CLEANED
        await db.flush()


async def segment_issue(
    db: AsyncSession,
    issue: Issue,
    newsletter: Newsletter,
    user_id,
) -> list[Article]:
    async with trace_stage(
        db, user_id, "segment",
        issue_id=issue.id, newsletter_id=newsletter.id,
        retry_count=issue.retry_count or 0,
    ):
        segments = segment_from_html(issue.raw_html or "", issue.subject)

        existing_result = await db.execute(select(Article).where(Article.issue_id == issue.id))
        existing_articles = existing_result.scalars().all()
        for existing in existing_articles:
            await db.delete(existing)

        articles: list[Article] = []
        for seg in segments:
            article = Article(
                issue_id=issue.id,
                user_id=user_id,
                newsletter_id=newsletter.id,
                title=seg.title,
                content_text=seg.content,
                url=seg.url,
                newsletter_link=seg.url,
                processing_status="segmented",
                published_at=issue.published_at,
                received_at=issue.received_at,
            )
            db.add(article)
            articles.append(article)

        newsletter.article_count = max(
            (newsletter.article_count or 0) - len(existing_articles) + len(articles),
            0,
        )
        issue.processing_status = PIPELINE_SEGMENTED
        await db.flush()
        return articles


async def process_issue_pipeline(
    db: AsyncSession,
    issue: Issue,
    newsletter: Newsletter,
    user_id,
) -> list[Article]:
    """Run phases 4-11 with full stage tracing."""
    try:
        if issue.processing_status == PIPELINE_IMPORTED:
            await clean_issue(db, issue, user_id, newsletter.id)

        issue.processing_status = PIPELINE_EXTRACTING
        await db.flush()

        articles = await segment_issue(db, issue, newsletter, user_id)

        extracted: list[Article] = []
        for article in articles:
            async with trace_stage(
                db, user_id, "extract",
                issue_id=issue.id, newsletter_id=newsletter.id, article_id=article.id,
                model_name=settings.extraction_model,
                prompt_version=settings.extraction_prompt_version,
                provider="openai",
            ) as tracer:
                await extract_and_embed_article(db, article, tracer=tracer)
                extracted.append(article)

            async with trace_stage(
                db, user_id, "embed",
                issue_id=issue.id, article_id=article.id,
                model_name=settings.embedding_model,
                provider="openai",
            ):
                pass  # embedding recorded inside extract

        async with trace_stage(
            db, user_id, "deduplicate",
            issue_id=issue.id, newsletter_id=newsletter.id,
        ):
            nl_names = {newsletter.id: newsletter.name}
            await deduplicate_articles(db, user_id, extracted, nl_names)

        async with trace_stage(db, user_id, "stored", issue_id=issue.id, newsletter_id=newsletter.id):
            issue.processing_status = PIPELINE_COMPLETED
            issue.processed_at = datetime.now(timezone.utc)
            issue.error_message = None
            await db.flush()

        return extracted

    except Exception as e:
        issue.processing_status = PIPELINE_FAILED
        issue.error_message = str(e)[:500]
        issue.retry_count = (issue.retry_count or 0) + 1
        await db.flush()
        log.error("pipeline_failed", issue_id=str(issue.id), error=str(e))
        raise


async def process_segmented_pipeline(
    db: AsyncSession,
    issue: Issue,
    newsletter: Newsletter,
    user_id,
) -> list[Article]:
    """Streaming pipeline tail: extract → embed → dedup (segment already done)."""
    try:
        issue.processing_status = PIPELINE_EXTRACTING
        await db.flush()

        result = await db.execute(select(Article).where(Article.issue_id == issue.id))
        articles = list(result.scalars().all())

        extracted: list[Article] = []
        for article in articles:
            async with trace_stage(
                db, user_id, "extract",
                issue_id=issue.id, newsletter_id=newsletter.id, article_id=article.id,
                model_name=settings.extraction_model,
                prompt_version=settings.extraction_prompt_version,
                provider="openai",
            ) as tracer:
                await extract_and_embed_article(db, article, tracer=tracer)
                extracted.append(article)

            async with trace_stage(
                db, user_id, "embed",
                issue_id=issue.id, article_id=article.id,
                model_name=settings.embedding_model,
                provider="openai",
            ):
                pass

        async with trace_stage(
            db, user_id, "deduplicate",
            issue_id=issue.id, newsletter_id=newsletter.id,
        ):
            nl_names = {newsletter.id: newsletter.name}
            await deduplicate_articles(db, user_id, extracted, nl_names)

        async with trace_stage(db, user_id, "stored", issue_id=issue.id, newsletter_id=newsletter.id):
            issue.processing_status = PIPELINE_COMPLETED
            issue.processed_at = datetime.now(timezone.utc)
            issue.error_message = None
            await db.flush()

        return extracted

    except Exception as e:
        issue.processing_status = PIPELINE_FAILED
        issue.error_message = str(e)[:500]
        issue.retry_count = (issue.retry_count or 0) + 1
        await db.flush()
        log.error("pipeline_failed", issue_id=str(issue.id), error=str(e))
        raise


async def process_issue_light(
    db: AsyncSession,
    issue: Issue,
    newsletter: Newsletter,
    user_id,
) -> list[Article]:
    """Fast path: clean + segment only — chat reads articles directly."""
    try:
        if issue.processing_status == PIPELINE_IMPORTED:
            await clean_issue(db, issue, user_id, newsletter.id)

        if issue.processing_status in (PIPELINE_IMPORTED, PIPELINE_CLEANED, PIPELINE_FAILED):
            articles = await segment_issue(db, issue, newsletter, user_id)
        else:
            result = await db.execute(select(Article).where(Article.issue_id == issue.id))
            articles = list(result.scalars().all())

        issue.processing_status = PIPELINE_COMPLETED
        issue.processed_at = datetime.now(timezone.utc)
        issue.error_message = None
        await db.flush()
        return articles

    except Exception as e:
        issue.processing_status = PIPELINE_FAILED
        issue.error_message = str(e)[:500]
        issue.retry_count = (issue.retry_count or 0) + 1
        await db.flush()
        log.error("pipeline_failed", issue_id=str(issue.id), error=str(e))
        raise


async def run_light_pipeline_batch(db: AsyncSession, user_id, limit: int = 20) -> dict:
    """Process pending issues without LLM — for local testing."""
    issues = await get_imported_issues(db, user_id, limit=limit)
    processed = 0
    articles_total = 0
    failed = 0
    for issue in issues:
        nl = (
            await db.execute(select(Newsletter).where(Newsletter.id == issue.newsletter_id))
        ).scalar_one_or_none()
        if not nl:
            continue
        try:
            arts = await process_issue_light(db, issue, nl, user_id)
            processed += 1
            articles_total += len(arts)
        except Exception:
            failed += 1
    return {"processed": processed, "failed": failed, "articles": articles_total}


async def get_imported_issues(db: AsyncSession, user_id, limit: int = 20) -> list[Issue]:
    result = await db.execute(
        select(Issue)
        .join(Newsletter)
        .where(
            Newsletter.user_id == user_id,
            Issue.processing_status.in_([
                PIPELINE_IMPORTED,
                PIPELINE_SEGMENTED,
                PIPELINE_FAILED,
            ]),
            Issue.retry_count < 5,
        )
        .order_by(Issue.received_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
