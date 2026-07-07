"""Phase 16.3: Breaking news and trending detection."""

from datetime import datetime, timezone

from app.config import get_settings
from app.models.article import CanonicalEvent, EventSource

settings = get_settings()


def detect_breaking_trending(event: CanonicalEvent, sources: list[EventSource]) -> None:
    """Mark events that appear across many newsletters within a short window."""
    event.is_trending = False
    event.is_breaking = False

    if len(sources) < settings.breaking_news_threshold:
        return

    now = datetime.now(timezone.utc)
    window_seconds = settings.breaking_news_window_hours * 3600

    timestamps = [s.created_at for s in sources if s.created_at]
    if event.first_appearance_at:
        timestamps.append(event.first_appearance_at)

    if len(timestamps) < 2:
        if len(sources) >= settings.trending_newsletter_threshold:
            event.is_trending = True
        return

    timestamps.sort()
    span = (timestamps[-1] - timestamps[0]).total_seconds()

    if len(sources) >= settings.trending_newsletter_threshold:
        event.is_trending = True

    if len(sources) >= settings.breaking_news_threshold and span <= window_seconds:
        event.is_breaking = True
        event.is_trending = True
