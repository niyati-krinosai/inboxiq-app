from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str | None
    picture: str | None
    initial_sync_complete: bool
    last_sync_at: datetime | None
    gmail_connected: bool = False
    sync_status: str = "idle"

    model_config = {"from_attributes": True}


class NewsletterResponse(BaseModel):
    id: UUID
    name: str
    sender_email: str
    domain: str | None = None
    frequency: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_sync_at: datetime | None = None
    issue_count: int
    article_count: int = 0
    processing_status: str = "discovered"

    model_config = {"from_attributes": True}


class EventSourceResponse(BaseModel):
    newsletter_name: str
    article_url: str | None
    summary_snippet: str | None


class CanonicalEventResponse(BaseModel):
    id: UUID
    headline: str
    primary_summary: str | None
    why_it_matters: str | None
    technical_impact: str | None
    business_impact: str | None
    categories: list[str] | None
    companies: list[str] | None
    products: list[str] | None
    frameworks: list[str] | None
    apis: list[str] | None
    technologies: list[str] | None
    official_link: str | None
    importance_score: float | None
    confidence: float | None
    first_appearance_at: datetime | None
    published_at: datetime | None
    sources: list[EventSourceResponse] = []

    model_config = {"from_attributes": True}


class TimelineResponse(BaseModel):
    events: list[CanonicalEventResponse]
    total: int
    timeline: str


class SearchResponse(BaseModel):
    events: list[CanonicalEventResponse]
    total: int
    query: str | None


class ChatRequest(BaseModel):
    question: str
    category: str | None = None
    timeline: str | None = None
    session_id: UUID | None = None
    article_id: UUID | None = None
    clear_article_context: bool = False


class ChatResponse(BaseModel):
    headline: str
    brief_summary: str
    why_it_matters: str = ""
    technical_impact: str | None = None
    business_impact: str | None = None
    sources: list[dict] = []
    official_link: str | None = None
    related_news: list[str] = []
    items: list[dict] = []  # lightweight: title, summary, url, newsletter
    verification: str | None = None
    confidence_score: float | None = None
    is_breaking: bool | None = None
    is_trending: bool | None = None
    session_id: str | None = None
    active_article: dict | None = None
    timeline_synthesis: list | None = None
    evolution_summary: str | None = None
    explanation: dict | None = None
    conflicts: list[dict] | None = None


class SyncStatusResponse(BaseModel):
    initial_sync_complete: bool
    last_sync_at: datetime | None
    newsletter_count: int
    issue_count: int
    article_count: int
    pending_processing: int = 0
    sync_status: str = "idle"
    gmail_connected: bool = False
