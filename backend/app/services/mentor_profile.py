"""Mentor-specific product overrides (Krishna = TLDR-only desk)."""

from __future__ import annotations

import uuid

KRISHNA_EMAIL = "krsgupta@ucdavis.edu"
KRISHNA_ID = uuid.UUID("6ec76ebf-2f36-4dfa-8ee0-620d51ed5b46")


def is_krishna_user(user) -> bool:
    email = (getattr(user, "email", None) or "").lower().strip()
    uid = getattr(user, "id", None)
    return email == KRISHNA_EMAIL or uid == KRISHNA_ID


def is_tldr_newsletter(newsletter) -> bool:
    name = (getattr(newsletter, "name", None) or "").lower()
    email = (getattr(newsletter, "sender_email", None) or "").lower()
    domain = (getattr(newsletter, "domain", None) or "").lower()
    return "tldr" in name or "tldr" in email or "tldr" in domain


def filter_tldr_newsletters(newsletters: list) -> list:
    return [nl for nl in newsletters if is_tldr_newsletter(nl)]
