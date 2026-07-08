"""Operational APIs — observability, costs, corrections, evals, push."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.article import Article
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.corrections import CORRECTION_TYPES, list_corrections, submit_correction
from app.services.eval_suite import run_eval_suite
from app.services.gmail_push import handle_pubsub_notification, register_gmail_watch
from app.services.llm_cost import get_user_cost_summary
from app.services.pipeline_dashboard import get_issue_pipeline_dashboard, list_pipeline_statuses
from app.services.retrieval_metrics import get_retrieval_metrics_summary

router = APIRouter(prefix="/ops", tags=["operations"])
settings = get_settings()


def _require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    if not settings.admin_secret:
        raise HTTPException(status_code=404, detail="Not found")
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


class CorrectionRequest(BaseModel):
    correction_type: str
    details: dict = {}
    event_id: UUID | None = None
    article_id: UUID | None = None


# ── 1 & 2: Pipeline tracing & dashboard ──────────────────────────────────────

@router.get("/pipeline")
async def pipeline_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, le=100),
):
    return await list_pipeline_statuses(db, user.id, limit)


@router.get("/pipeline/{issue_id}")
async def pipeline_detail(
    issue_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dash = await get_issue_pipeline_dashboard(db, user.id, issue_id)
    if not dash:
        raise HTTPException(status_code=404, detail="Issue not found")
    return dash


# ── 3: LLM cost tracking ─────────────────────────────────────────────────────

@router.get("/costs")
async def llm_costs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_user_cost_summary(db, user.id)


@router.get("/model-versions")
async def model_versions():
    return settings.model_versions()


# ── 4: Quality evaluation suite ──────────────────────────────────────────────

@router.post("/eval/run")
async def run_eval(user: User = Depends(get_current_user)):
    return run_eval_suite()


# ── 5: Human-in-the-loop corrections ─────────────────────────────────────────

@router.post("/corrections")
async def create_correction(
    body: CorrectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        correction = await submit_correction(
            db, user.id, body.correction_type, body.details,
            body.event_id, body.article_id,
        )
        await db.commit()
        return {"id": str(correction.id), "status": "submitted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/corrections")
async def get_corrections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    corrections = await list_corrections(db, user.id)
    return [
        {
            "id": str(c.id),
            "type": c.correction_type,
            "details": c.details,
            "event_id": str(c.event_id) if c.event_id else None,
            "applied": c.applied,
            "created_at": c.created_at.isoformat(),
        }
        for c in corrections
    ]


@router.get("/corrections/types")
async def correction_types():
    return {"types": sorted(CORRECTION_TYPES)}


# ── 6: Retrieval metrics ─────────────────────────────────────────────────────

@router.get("/retrieval-metrics")
async def retrieval_metrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_retrieval_metrics_summary(db, user.id)


# ── 10: Gmail Push webhook ───────────────────────────────────────────────────

@router.post("/gmail/webhook")
async def gmail_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive Gmail Pub/Sub push notifications."""
    if settings.gmail_webhook_secret:
        token = request.headers.get("X-Webhook-Secret", "")
        if token != settings.gmail_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    body = await request.json()
    result = await handle_pubsub_notification(db, body)
    await db.commit()
    return result


@router.post("/gmail/watch")
async def setup_gmail_watch(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await register_gmail_watch(db, user)
    await db.commit()
    return result


# ── Admin support (set ADMIN_SECRET on Render; header X-Admin-Secret) ─────────

@router.get("/admin/users")
async def admin_list_users(
    search: str = Query("", max_length=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    stmt = select(User).order_by(User.created_at.desc())
    if search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))
    users = list((await db.execute(stmt)).scalars().all())
    out = []
    for u in users:
        nl = (await db.execute(select(func.count()).where(Newsletter.user_id == u.id))).scalar() or 0
        arts = (await db.execute(select(func.count()).where(Article.user_id == u.id))).scalar() or 0
        out.append({
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "gmail_connected": u.gmail_connected,
            "sync_status": u.sync_status,
            "initial_sync_complete": u.initial_sync_complete,
            "newsletter_count": nl,
            "article_count": arts,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return {"users": out, "count": len(out)}


@router.post("/admin/force-sync")
async def admin_force_sync(
    background_tasks: BackgroundTasks,
    email: str = Query(..., min_length=3),
    reset: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    from app.api.routes import _queue_gmail_sync, _run_light_pipeline

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.gmail_connected:
        raise HTTPException(status_code=400, detail="Gmail not connected for this user")

    if reset:
        user.initial_sync_complete = False
        user.sync_status = "idle"
        await db.commit()

    _queue_gmail_sync(background_tasks, user.id)
    background_tasks.add_task(_run_light_pipeline, user.id)
    return {
        "status": "sync_started",
        "user_id": str(user.id),
        "email": user.email,
        "reset": reset,
    }
