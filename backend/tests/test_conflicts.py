"""Unit tests for conflict detection."""

import uuid

from app.services.conflict_detection import _find_conflicts, format_conflicts_for_chat
from app.models.event_sourcing import EventConflict


def test_find_funding_conflicts():
    claims = [
        {"field": "funding_amount", "value": "$40M", "source": "a"},
        {"field": "funding_amount", "value": "$50M", "source": "b"},
    ]
    conflicts = _find_conflicts(claims)
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "funding_amount"
    assert len(conflicts[0]["claims"]) == 2


def test_no_conflict_same_value():
    claims = [
        {"field": "funding_amount", "value": "$50M", "source": "a"},
        {"field": "funding_amount", "value": "$50M", "source": "b"},
    ]
    assert _find_conflicts(claims) == []


def test_format_conflicts_for_chat():
    conflict = EventConflict(
        id=uuid.uuid4(),
        canonical_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        field="funding_amount",
        claims=[{"value": "$40M"}, {"value": "$50M"}],
        status="open",
    )
    lines = format_conflicts_for_chat([conflict])
    assert len(lines) == 1
    assert "$40M" in lines[0] and "$50M" in lines[0]
