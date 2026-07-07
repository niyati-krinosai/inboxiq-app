import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserInterestProfile(Base):
    """Phase 17: learned interest profile from user behavior."""

    __tablename__ = "user_interest_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    category_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {"AI": 0.8, ...}
    topic_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    company_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    favorite_newsletter_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserActivity(Base):
    """Tracks clicks, searches, and questions for personalization."""

    __tablename__ = "user_activities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    activity_type: Mapped[str] = mapped_column(String(32))  # click|search|question|view_event
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    """Phase 18: conversational memory per session."""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    context_topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    context_entities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DailyDigest(Base):
    """Phase 24: generated morning digest per user."""

    __tablename__ = "daily_digests"
    __table_args__ = (UniqueConstraint("user_id", "digest_date", name="uq_user_digest_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    digest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
