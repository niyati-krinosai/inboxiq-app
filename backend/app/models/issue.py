import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Pipeline stages — import is separate from intelligence processing
PIPELINE_IMPORTED = "imported"
PIPELINE_CLEANED = "cleaned"
PIPELINE_SEGMENTED = "segmented"
PIPELINE_EXTRACTING = "extracting"
PIPELINE_COMPLETED = "completed"
PIPELINE_FAILED = "failed"


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("newsletter_id", "gmail_message_id", name="uq_newsletter_message"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    newsletter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("newsletters.id", ondelete="CASCADE")
    )

    gmail_message_id: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headers_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Phase 3: raw import only
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 4: cleaned content
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    processing_status: Mapped[str] = mapped_column(String(32), default=PIPELINE_IMPORTED)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    newsletter: Mapped["Newsletter"] = relationship(back_populates="issues")
    articles: Mapped[list["Article"]] = relationship(back_populates="issue", cascade="all, delete-orphan")
