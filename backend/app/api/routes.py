import uuid
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, get_db
from app.dependencies import get_current_user
from app.core.logging import get_logger
from app.models.article import Article, CanonicalEvent, EventSource
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.user import User
from app.schemas import (
    ChatRequest,
    ChatResponse,
    EventSourceResponse,
    NewsletterResponse,
    SearchResponse,
    SyncStatusResponse,
    TimelineResponse,
    UserResponse,
)
from app.services.auth import create_access_token
from app.services.chat import chat
from app.services.simple_chat import simple_chat
from app.services.google_oauth import (
    build_frontend_redirect,
    disconnect_gmail,
    exchange_code_for_tokens,
    get_authorization_url,
    get_user_info,
    verify_oauth_state,
    upsert_user_from_google,
)
from app.services.search import (
    get_newsletter_articles,
    get_newsletter_detail,
    get_newsletters,
    get_timeline_events,
    search_events,
)
from app.services.pipeline import run_light_pipeline_batch
from app.services.gmail_sync import initial_sync, incremental_sync
from app.workers.tasks import sync_user_gmail

router = APIRouter()
settings = get_settings()
log = get_logger(__name__)


async def _run_light_pipeline(user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await run_light_pipeline_batch(db, user_id, limit=50)
            await db.commit()
            log.info("light_pipeline_done", user_id=str(user_id), **result)
        except Exception as exc:
            await db.rollback()
            log.error("light_pipeline_failed", user_id=str(user_id), error=str(exc))


_sync_inflight: set[str] = set()


def _queue_gmail_sync(background_tasks: BackgroundTasks | None, user_id: uuid.UUID) -> None:
    """Run Gmail sync on Render without Celery (BackgroundTasks are unreliable there)."""
    if settings.use_celery:
        if background_tasks:
            background_tasks.add_task(_run_gmail_sync, user_id)
        try:
            sync_user_gmail.delay(str(user_id))
        except Exception as exc:
            log.warning("celery_sync_unavailable", error=str(exc))
    else:
        asyncio.create_task(_run_gmail_sync(user_id))


async def _run_gmail_sync(user_id: uuid.UUID) -> None:
    """Fallback when Celery is not running."""
    key = str(user_id)
    if key in _sync_inflight:
        log.info("gmail_sync_skipped_inflight", user_id=key)
        return
    _sync_inflight.add(key)
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not user.gmail_connected:
                return
            user.sync_status = "syncing"
            await db.commit()

            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return

            if not user.initial_sync_complete:
                await initial_sync(db, user)
            else:
                await incremental_sync(db, user)
            await db.commit()
            log.info("inline_gmail_sync_done", user_id=key)
            await _run_light_pipeline(user_id)
        except Exception as exc:
            await db.rollback()
            try:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user:
                    user.sync_status = "failed"
                    await db.commit()
            except Exception:
                await db.rollback()
            log.error("inline_gmail_sync_failed", user_id=key, error=str(exc))
        finally:
            _sync_inflight.discard(key)


def _event_to_response(event) -> dict:
    sources = [
        EventSourceResponse(
            newsletter_name=s.newsletter_name,
            article_url=s.article_url,
            summary_snippet=s.summary_snippet,
        )
        for s in (event.sources or [])
    ]
    return {
        "id": event.id,
        "headline": event.headline,
        "primary_summary": event.primary_summary,
        "why_it_matters": event.why_it_matters,
        "technical_impact": event.technical_impact,
        "business_impact": event.business_impact,
        "categories": event.categories,
        "companies": event.companies,
        "products": event.products,
        "frameworks": event.frameworks,
        "apis": event.apis,
        "technologies": event.technologies,
        "official_link": event.official_link,
        "importance_score": event.importance_score,
        "ranking_score": event.ranking_score,
        "confidence": event.confidence,
        "confidence_score": event.confidence_score,
        "verification_level": event.verification_level,
        "is_breaking": event.is_breaking,
        "is_trending": event.is_trending,
        "newsletter_count": event.newsletter_count,
        "canonical_title": event.canonical_title,
        "first_appearance_at": event.first_appearance_at,
        "published_at": event.published_at,
        "sources": sources,
    }


# ── Phase 1: Google OAuth (read-only Gmail) ──────────────────────────────────

@router.get("/auth/login")
async def login():
    return get_authorization_url()


@router.get("/auth/callback")
async def auth_callback(
    background_tasks: BackgroundTasks,
    code: str,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    stage = "receive_callback"
    try:
        log.info("oauth_callback_enter", stage=stage, code_present=bool(code), state_present=bool(state))

        # Exchange authorization code for tokens (confidential client, no PKCE)
        stage = "exchange_code"
        log.info("oauth_stage", stage=stage)
        credentials, id_token = exchange_code_for_tokens(code, state)
        log.info("oauth_stage_done", stage=stage, scopes=list(credentials.scopes or []))

        # Decode / get user info
        stage = "get_user_info"
        log.info("oauth_stage", stage=stage)
        user_info = get_user_info(credentials, id_token)
        log.info("oauth_stage_done", stage=stage, email=user_info.get("email"))

        # Persist user and credentials
        stage = "upsert_user"
        log.info("oauth_stage", stage=stage)
        user = await upsert_user_from_google(db, user_info, credentials)
        await db.commit()
        log.info("oauth_stage_done", stage=stage, user_id=str(user.id))

        # Generate JWT
        stage = "generate_jwt"
        log.info("oauth_stage", stage=stage)
        token = create_access_token(user.id, user.email)
        log.info("oauth_stage_done", stage=stage)

        # Queue initial Gmail sync (inline on Render — Celery optional)
        stage = "queue_sync"
        _queue_gmail_sync(background_tasks, user.id)
        log.info("oauth_stage_done", stage=stage, user_id=str(user.id))

        # Optionally register Pub/Sub watch (best effort)
        if settings.gmail_pubsub_topic:
            stage = "register_gmail_watch"
            try:
                from app.services.gmail_push import register_gmail_watch
                await register_gmail_watch(db, user)
                await db.commit()
                log.info("oauth_stage_done", stage=stage)
            except Exception as e:
                log.warning("gmail_watch_failed", stage=stage, reason=str(e))

        # Redirect back to frontend
        stage = "redirect"
        redirect_url = build_frontend_redirect(token)
        log.info("oauth_completed", stage=stage, redirect=redirect_url)
        return RedirectResponse(redirect_url)

    except ValueError as e:
        log.error("oauth_failed", stage=stage, reason=str(e))
        return RedirectResponse(build_frontend_redirect(error=str(e)))
    except Exception as e:
        log.exception("oauth_callback_exception", stage=stage, error=str(e))
        return RedirectResponse(build_frontend_redirect(error="Sign-in failed. Please try again."))


@router.get("/auth/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/auth/disconnect")
async def disconnect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Phase 15: revoke Gmail connection (tokens cleared, data retained)."""
    await disconnect_gmail(db, user)
    await db.commit()
    return {"status": "disconnected"}


@router.delete("/auth/account")
async def delete_account(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Phase 15: permanently delete all imported data and disconnect Gmail."""
    from sqlalchemy import delete as sql_delete

    uid = user.id
    await db.execute(sql_delete(EventSource).where(
        EventSource.canonical_event_id.in_(
            select(CanonicalEvent.id).where(CanonicalEvent.user_id == uid)
        )
    ))
    from app.models.knowledge_graph import EntityRelation, KnowledgeEntity
    await db.execute(sql_delete(EntityRelation).where(EntityRelation.user_id == uid))
    await db.execute(sql_delete(KnowledgeEntity).where(KnowledgeEntity.user_id == uid))
    await db.execute(sql_delete(Article).where(Article.user_id == uid))
    await db.execute(sql_delete(CanonicalEvent).where(CanonicalEvent.user_id == uid))
    await db.execute(sql_delete(Issue).where(
        Issue.newsletter_id.in_(select(Newsletter.id).where(Newsletter.user_id == uid))
    ))
    await db.execute(sql_delete(Newsletter).where(Newsletter.user_id == uid))
    await disconnect_gmail(db, user)
    await db.delete(user)
    await db.commit()
    return {"status": "account_deleted"}


# ── Sync status ───────────────────────────────────────────────────────────────

@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    nl_count = (await db.execute(select(func.count()).where(Newsletter.user_id == user.id))).scalar() or 0
    issue_count = (await db.execute(
        select(func.count()).select_from(Issue).join(Newsletter).where(Newsletter.user_id == user.id)
    )).scalar() or 0
    article_count = (await db.execute(select(func.count()).where(Article.user_id == user.id))).scalar() or 0

    pending = (await db.execute(
        select(func.count()).select_from(Issue).join(Newsletter).where(
            Newsletter.user_id == user.id,
            Issue.processing_status.in_(["imported", "segmented", "failed"]),
        )
    )).scalar() or 0

    # Recover stuck syncs (BackgroundTask killed, Celery never ran, or status stuck on "syncing")
    stuck_syncing = (
        user.sync_status == "syncing"
        and not user.initial_sync_complete
        and user.updated_at
        and user.updated_at < datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    if stuck_syncing:
        user.sync_status = "idle"
        await db.commit()
    if user.gmail_connected and not user.initial_sync_complete and user.sync_status != "syncing":
        _queue_gmail_sync(background_tasks, user.id)
    elif user.gmail_connected and (pending > 0 or (article_count == 0 and issue_count > 0)):
        background_tasks.add_task(_run_light_pipeline, user.id)

    return SyncStatusResponse(
        initial_sync_complete=user.initial_sync_complete,
        last_sync_at=user.last_sync_at,
        newsletter_count=nl_count,
        issue_count=issue_count,
        article_count=article_count,
        pending_processing=pending,
        sync_status=user.sync_status,
        gmail_connected=user.gmail_connected,
    )


@router.post("/sync/trigger")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    if not user.gmail_connected:
        raise HTTPException(status_code=400, detail="Gmail not connected")
    if not settings.use_celery:
        await _run_gmail_sync(user.id)
        if settings.simple_mode:
            await _run_light_pipeline(user.id)
        return {"status": "sync_complete"}
    _queue_gmail_sync(background_tasks, user.id)
    if settings.simple_mode:
        background_tasks.add_task(_run_light_pipeline, user.id)
    return {"status": "sync_started"}


@router.post("/sync/process")
async def process_newsletters(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Extract articles from imported newsletter issues (no LLM, fast)."""
    if settings.simple_mode:
        background_tasks.add_task(_run_light_pipeline, user.id)
        return {"status": "processing_started"}
    try:
        from app.workers.tasks import run_intelligence_pipeline
        run_intelligence_pipeline.delay(str(user.id))
        return {"status": "processing_started"}
    except Exception as exc:
        log.warning("celery_pipeline_unavailable", error=str(exc))
        background_tasks.add_task(_run_light_pipeline, user.id)
        return {"status": "processing_started", "mode": "inline"}


# ── Phase 13: Source Explorer API ─────────────────────────────────────────────

@router.get("/newsletters", response_model=list[NewsletterResponse])
async def list_newsletters(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    newsletters = await get_newsletters(db, user.id)
    result = []
    for nl in newsletters:
        detail = await get_newsletter_detail(db, nl.id, user.id)
        if detail:
            result.append(detail)
    return result


@router.get("/newsletters/{newsletter_id}")
async def get_newsletter(
    newsletter_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    detail = await get_newsletter_detail(db, newsletter_id, user.id)
    if not detail:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return detail


@router.get("/newsletters/{newsletter_id}/articles")
async def newsletter_articles(
    newsletter_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(500, le=5000),
):
    articles = await get_newsletter_articles(db, newsletter_id, user.id, limit)
    return [
        {
            "id": a.id,
            "title": a.title,
            "short_summary": a.short_summary,
            "categories": a.categories,
            "importance_score": a.importance_score,
            "received_at": a.received_at,
            "processed_at": a.processed_at,
            "url": a.url,
            "official_link": a.official_link,
        }
        for a in articles
    ]


# ── Phase 10: Timeline ────────────────────────────────────────────────────────

@router.get("/timeline", response_model=TimelineResponse)
async def timeline(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    filter: str = Query("1w", alias="filter"),
    category: str | None = None,
    limit: int = Query(50, le=100),
):
    events = await get_timeline_events(db, user.id, timeline=filter, category=category, limit=limit)
    return TimelineResponse(
        events=[_event_to_response(e) for e in events],
        total=len(events),
        timeline=filter,
    )


# ── Phase 12: Search ──────────────────────────────────────────────────────────

@router.get("/search", response_model=SearchResponse)
async def search(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    q: str | None = None,
    category: str | None = None,
    timeline: str | None = None,
    entity_type: str | None = None,
    entity_value: str | None = None,
    semantic: bool = Query(True),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
):
    events, total = await search_events(
        db, user.id, query=q, category=category, timeline=timeline,
        entity_type=entity_type, entity_value=entity_value,
        limit=limit, offset=offset, semantic=semantic,
    )
    return SearchResponse(events=[_event_to_response(e) for e in events], total=total, query=q)


# ── Phase 11: Chatbot ─────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        if settings.simple_mode:
            result = await simple_chat(
                db,
                user.id,
                body.question,
                body.category,
                body.timeline,
                body.session_id,
                body.article_id,
                body.clear_article_context,
            )
        else:
            result = await chat(
                db, user.id, body.question, body.category, body.timeline, body.session_id
            )
    except Exception as exc:
        log.exception("chat_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Chat failed. Try again in a moment.")

    return ChatResponse(
        headline=result.get("headline", ""),
        brief_summary=result.get("brief_summary", ""),
        why_it_matters=result.get("why_it_matters", ""),
        technical_impact=result.get("technical_impact"),
        business_impact=result.get("business_impact"),
        sources=result.get("sources", []),
        official_link=result.get("official_link"),
        related_news=result.get("related_news", []),
        items=result.get("items", []),
        verification=result.get("verification"),
        confidence_score=result.get("confidence_score"),
        is_breaking=result.get("is_breaking"),
        is_trending=result.get("is_trending"),
        session_id=result.get("session_id"),
        active_article=result.get("active_article"),
        timeline_synthesis=result.get("timeline_synthesis"),
        evolution_summary=result.get("evolution_summary"),
        explanation=result.get("explanation"),
        conflicts=result.get("conflicts"),
    )


@router.get("/categories")
async def list_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.constants import CATEGORIES
    from app.services.user_modes import discover_user_modes

    personal = await discover_user_modes(db, user.id)
    return {"categories": CATEGORIES, "personal_modes": personal}
