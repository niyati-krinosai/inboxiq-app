from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.intelligence import router as intelligence_router
from app.api.knowledge import router as knowledge_router
from app.api.operations import router as operations_router
from app.api.routes import router
from app.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit_api import RateLimitMiddleware
from app.database import engine

settings = get_settings()
setup_logging()
log = get_logger(__name__)


def _cors_origins() -> list[str]:
    origins = {settings.frontend_url, "http://localhost:3000"}
    if settings.cors_extra_origins:
        origins.update(o.strip() for o in settings.cors_extra_origins.split(",") if o.strip())
    return list(origins)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            log.warning("pgvector_unavailable", error=str(exc))
        from app.database import Base
        from app.models import (  # noqa: F401
            Article,
            CanonicalEvent,
            CanonicalEventVersion,
            ChatSession,
            DailyDigest,
            EntityRelation,
            EventConflict,
            EventSource,
            GmailWatch,
            Issue,
            KnowledgeEntity,
            LLMUsageLog,
            Newsletter,
            PipelineStageTrace,
            PromptRegistry,
            RetrievalMetric,
            User,
            UserActivity,
            UserCorrection,
            UserInterestProfile,
            UserTaxonomy,
        )
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.api_rate_limit_rpm)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_prefix)
app.include_router(intelligence_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(operations_router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
