import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CanonicalEventVersion(Base):
    """Immutable version log for canonical events — Git history for news."""

    __tablename__ = "canonical_event_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    version: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(64))  # created|merged_sources|updated_summary|conflict_resolved
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    snapshot: Mapped[dict] = mapped_column(JSONB)  # full event state at this version
    merged_source_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventConflict(Base):
    """Conflicting claims from different newsletter sources."""

    __tablename__ = "event_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_events.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    field: Mapped[str] = mapped_column(String(64))  # funding_amount|release_date|company_name
    claims: Mapped[list] = mapped_column(JSONB)  # [{source, value, newsletter, url}]
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_source: Mapped[str | None] = mapped_column(String(32), nullable=True)  # official_filing|majority|manual
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|resolved|ignored

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserTaxonomy(Base):
    """User-defined category collections."""

    __tablename__ = "user_taxonomies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB)  # ["OpenAI", "LangGraph", "MCP"]
    entity_filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptRegistry(Base):
    """Versioned prompts — change without touching code."""

    __tablename__ = "prompt_registry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), index=True)  # extraction|chat|canonicalize
    version: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|eval|production|archived
    eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
