import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database import Base

settings = get_settings()


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issue_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    newsletter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("newsletters.id", ondelete="CASCADE")
    )
    canonical_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_events.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(1024))
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    newsletter_link: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    categories: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(255), nullable=True)
    companies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    frameworks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    apis: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    models: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    repositories: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    people: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    technologies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    funding: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    importance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    novelty_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    short_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    developer_takeaway: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_impact: Mapped[str | None] = mapped_column(Text, nullable=True)

    official_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    embedding: Mapped[list | None] = mapped_column(Vector(settings.embedding_dimensions), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="segmented")

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped["Issue"] = relationship(back_populates="articles")
    canonical_event: Mapped["CanonicalEvent | None"] = relationship(back_populates="articles")
    event_sources: Mapped[list["EventSource"]] = relationship(back_populates="article")


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    headline: Mapped[str] = mapped_column(String(1024))
    canonical_title: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # launch|funding|api_release|...

    primary_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    developer_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_changes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    timeline_entries: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    categories: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    companies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    frameworks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    apis: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    models: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    repositories: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    technologies: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    official_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    alternative_explanations: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    importance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ranking_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_level: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_trending: Mapped[bool] = mapped_column(default=False)
    is_breaking: Mapped[bool] = mapped_column(default=False)
    newsletter_count: Mapped[int] = mapped_column(default=0)
    importance_factors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    embedding: Mapped[list | None] = mapped_column(Vector(settings.embedding_dimensions), nullable=True)

    first_appearance_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Knowledge freshness
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_newsletter_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_official_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    staleness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    articles: Mapped[list["Article"]] = relationship(back_populates="canonical_event")
    sources: Mapped[list["EventSource"]] = relationship(
        back_populates="canonical_event", cascade="all, delete-orphan"
    )


class EventSource(Base):
    __tablename__ = "event_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_events.id", ondelete="CASCADE")
    )
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"))
    newsletter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("newsletters.id", ondelete="CASCADE")
    )

    newsletter_name: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32), default="newsletter")
    source_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    article_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    canonical_event: Mapped["CanonicalEvent"] = relationship(back_populates="sources")
    article: Mapped["Article"] = relationship(back_populates="event_sources")
