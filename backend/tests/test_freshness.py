"""Unit tests for knowledge freshness scoring."""

from datetime import datetime, timedelta, timezone

from app.services.freshness import compute_staleness_score, apply_freshness_to_event
from app.models.article import CanonicalEvent


def test_staleness_fresh():
    now = datetime.now(timezone.utc)
    score = compute_staleness_score(now - timedelta(days=1), now, now)
    assert score == 0.0


def test_staleness_week_old():
    now = datetime.now(timezone.utc)
    score = compute_staleness_score(now - timedelta(days=10), None, None)
    assert 0.15 <= score <= 0.55


def test_staleness_very_old():
    now = datetime.now(timezone.utc)
    score = compute_staleness_score(now - timedelta(days=60), None, None)
    assert score >= 0.7


def test_apply_freshness_degrades_confidence():
    event = CanonicalEvent(
        headline="Test",
        confidence_score=0.9,
        last_newsletter_seen=datetime.now(timezone.utc) - timedelta(days=45),
    )
    apply_freshness_to_event(event)
    assert event.staleness_score is not None
    assert event.confidence_score < 0.9
