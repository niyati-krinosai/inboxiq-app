"""Knowledge infrastructure APIs — event sourcing, conflicts, taxonomy, prompts, connectors."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import CONNECTOR_REGISTRY, get_connector
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.conflict_detection import list_event_conflicts, resolve_conflict
from app.services.event_sourcing import get_event_history, rebuild_event_at_version
from app.services.freshness import refresh_stale_events
from app.services.prompt_registry import list_prompts, promote_prompt, register_prompt, rollback_prompt
from app.services.taxonomy import create_taxonomy, list_taxonomies, match_events_to_taxonomy

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class TaxonomyRequest(BaseModel):
    name: str
    tags: list[str]
    description: str | None = None
    entity_filters: dict | None = None


class PromptRequest(BaseModel):
    name: str
    version: str
    content: str
    status: str = "draft"
    notes: str | None = None


class ConflictResolveRequest(BaseModel):
    resolved_value: str
    resolution: str
    resolved_source: str = "manual"


@router.get("/events/{event_id}/history")
async def event_history(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Immutable version log for a canonical event."""
    history = await get_event_history(db, user.id, event_id)
    if not history:
        raise HTTPException(status_code=404, detail="Event or history not found")
    return {"event_id": str(event_id), "versions": history}


@router.get("/events/{event_id}/history/{version}")
async def event_at_version(
    event_id: UUID,
    version: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    snapshot = await rebuild_event_at_version(db, user.id, event_id, version)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"event_id": str(event_id), "version": version, "snapshot": snapshot}


@router.get("/events/{event_id}/conflicts")
async def event_conflicts(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conflicts = await list_event_conflicts(db, user.id, event_id)
    return [
        {
            "id": str(c.id),
            "field": c.field,
            "claims": c.claims,
            "status": c.status,
            "resolution": c.resolution,
            "resolved_value": c.resolved_value,
            "resolved_source": c.resolved_source,
        }
        for c in conflicts
    ]


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_event_conflict(
    conflict_id: UUID,
    body: ConflictResolveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conflict = await resolve_conflict(
        db, conflict_id, user.id,
        body.resolved_value, body.resolution, body.resolved_source,
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")
    await db.commit()
    return {"status": "resolved", "id": str(conflict.id)}


@router.post("/taxonomy")
async def create_user_taxonomy(
    body: TaxonomyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    taxonomy = await create_taxonomy(
        db, user.id, body.name, body.tags, body.description, body.entity_filters,
    )
    await db.commit()
    return {"id": str(taxonomy.id), "name": taxonomy.name, "tags": taxonomy.tags}


@router.get("/taxonomy")
async def get_taxonomies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    taxonomies = await list_taxonomies(db, user.id)
    return [
        {"id": str(t.id), "name": t.name, "tags": t.tags, "description": t.description}
        for t in taxonomies
    ]


@router.get("/taxonomy/{taxonomy_id}/events")
async def taxonomy_events(
    taxonomy_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=100),
):
    taxonomies = await list_taxonomies(db, user.id)
    taxonomy = next((t for t in taxonomies if t.id == taxonomy_id), None)
    if not taxonomy:
        raise HTTPException(status_code=404, detail="Taxonomy not found")
    events = await match_events_to_taxonomy(db, user.id, taxonomy, limit)
    return [
        {
            "id": str(e.id),
            "canonical_title": e.canonical_title,
            "headline": e.headline,
            "confidence_score": e.confidence_score,
            "staleness_score": e.staleness_score,
        }
        for e in events
    ]


@router.get("/prompts")
async def get_prompts(
    name: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_prompts(db, name)


@router.post("/prompts")
async def create_prompt(
    body: PromptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prompt = await register_prompt(
        db, body.name, body.version, body.content, body.status, body.notes,
    )
    await db.commit()
    return {"id": str(prompt.id), "name": prompt.name, "version": prompt.version, "status": prompt.status}


@router.post("/prompts/{name}/{version}/promote")
async def promote_prompt_version(
    name: str,
    version: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prompt = await promote_prompt(db, name, version)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    await db.commit()
    return {"name": prompt.name, "version": prompt.version, "status": prompt.status}


@router.post("/prompts/{name}/rollback")
async def rollback_prompt_version(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prompt = await rollback_prompt(db, name)
    if not prompt:
        raise HTTPException(status_code=404, detail="No archived prompt to rollback")
    await db.commit()
    return {"name": prompt.name, "version": prompt.version, "status": prompt.status}


@router.get("/connectors")
async def list_connectors(user: User = Depends(get_current_user)):
    return {"available": list(CONNECTOR_REGISTRY.keys())}


@router.get("/connectors/{source_type}/discover")
async def discover_sources(
    source_type: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        connector = get_connector(source_type, db, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sources = await connector.discover()
    return [{"name": s.name, "identifier": s.identifier, "type": s.source_type} for s in sources]


@router.post("/freshness/refresh")
async def refresh_freshness(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await refresh_stale_events(db, user.id)
    await db.commit()
    return {"refreshed_events": count}
