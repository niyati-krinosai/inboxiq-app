import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import KNOWN_NEWSLETTER_DOMAINS, KNOWN_NEWSLETTER_LABELS
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.services.newsletter_discovery import (
    DetectionResult,
    detect_newsletter,
    detection_signals_to_json,
)


def estimate_frequency(issue_dates: list[datetime]) -> str:
    """Estimate newsletter frequency from issue timestamps."""
    if len(issue_dates) < 2:
        return "irregular"

    sorted_dates = sorted(issue_dates, reverse=True)
    gaps = []
    for i in range(len(sorted_dates) - 1):
        gap = (sorted_dates[i] - sorted_dates[i + 1]).total_seconds() / 86400
        if gap > 0:
            gaps.append(gap)

    if not gaps:
        return "irregular"

    avg_gap = sum(gaps) / len(gaps)
    if avg_gap <= 2:
        return "daily"
    if avg_gap <= 10:
        return "weekly"
    if avg_gap <= 20:
        return "biweekly"
    if avg_gap <= 40:
        return "monthly"
    return "irregular"


async def update_newsletter_frequency(
    db: AsyncSession,
    newsletter: Newsletter,
) -> None:
    result = await db.execute(
        select(Issue.received_at)
        .where(Issue.newsletter_id == newsletter.id)
        .order_by(Issue.received_at.desc())
        .limit(20)
    )
    dates = [row[0] for row in result.all()]
    newsletter.frequency = estimate_frequency(dates)


def _is_tldr_detection(detection: DetectionResult) -> bool:
    domain = (detection.domain or "").lower()
    name = (detection.sender_name or "").lower()
    email = (detection.sender_email or "").lower()
    return (
        "tldr" in domain
        or "tldr" in name
        or "tldrnewsletter.com" in email
        or "tldr.tech" in email
    )


def _tldr_storage_email(detection: DetectionResult, name: str) -> str:
    """TLDR products share dan@tldrnewsletter.com — use a per-product email key."""
    domain = detection.domain or "tldrnewsletter.com"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tldr"
    return f"{slug}@{domain}"


async def register_newsletter(
    db: AsyncSession,
    user_id,
    detection: DetectionResult,
    received_at: datetime,
) -> Newsletter:
    name = _resolve_newsletter_name(detection)
    is_tldr = _is_tldr_detection(detection)
    storage_email = (
        _tldr_storage_email(detection, name) if is_tldr else detection.sender_email
    )

    if is_tldr:
        # Match by product name so TLDR AI / TLDR Marketing stay separate
        result = await db.execute(
            select(Newsletter).where(
                Newsletter.user_id == user_id,
                Newsletter.name == name,
            )
        )
        newsletter = result.scalar_one_or_none()
        if not newsletter:
            # Legacy row keyed only by shared dan@ email
            result = await db.execute(
                select(Newsletter).where(
                    Newsletter.user_id == user_id,
                    Newsletter.sender_email == detection.sender_email,
                    Newsletter.name == name,
                )
            )
            newsletter = result.scalar_one_or_none()
    else:
        result = await db.execute(
            select(Newsletter).where(
                Newsletter.user_id == user_id,
                Newsletter.sender_email == detection.sender_email,
            )
        )
        newsletter = result.scalar_one_or_none()

    if newsletter:
        newsletter.last_seen_at = max(newsletter.last_seen_at, received_at)
        if detection.sender_name and not newsletter.sender_name:
            newsletter.sender_name = detection.sender_name
        if is_tldr and newsletter.sender_email == detection.sender_email:
            # Migrate legacy shared-email row to per-product key when safe
            clash = await db.execute(
                select(Newsletter).where(
                    Newsletter.user_id == user_id,
                    Newsletter.sender_email == storage_email,
                    Newsletter.id != newsletter.id,
                )
            )
            if clash.scalar_one_or_none() is None:
                newsletter.sender_email = storage_email
        return newsletter

    newsletter = Newsletter(
        user_id=user_id,
        name=name,
        sender_email=storage_email,
        sender_name=detection.sender_name or None,
        domain=detection.domain or None,
        detection_signals=detection_signals_to_json(detection.signals),
        first_seen_at=received_at,
        last_seen_at=received_at,
        issue_count=0,
        article_count=0,
        processing_status="discovered",
    )
    db.add(newsletter)
    await db.flush()
    return newsletter


def _humanize_sender(email: str) -> str:
    local = email.split("@")[0]
    return re.sub(r"[._-]", " ", local).title()


def _resolve_newsletter_name(detection: DetectionResult) -> str:
    """Prefer brand names (TLDR, etc.) over raw sender display names."""
    if detection.sender_name:
        lower = detection.sender_name.lower()
        if "tldr" in lower:
            return detection.sender_name.strip()
    domain = detection.domain or ""
    for known, label in KNOWN_NEWSLETTER_LABELS.items():
        if domain == known or domain.endswith("." + known):
            if detection.sender_name and "tldr" in detection.sender_name.lower():
                return detection.sender_name.strip()
            return label
    return detection.sender_name or _humanize_sender(detection.sender_email)


def is_personal_email(detection: DetectionResult, headers: list[dict]) -> bool:
    """Exclude likely personal emails even if they have some bulk signals."""
    if detection.confidence >= 0.6:
        return False

    # Very low confidence with no list headers = personal
    has_list_header = any(
        s.startswith("list-") or s == "precedence-bulk"
        for s in detection.signals
    )
    if not has_list_header and detection.confidence < 0.45:
        return True

    # Known newsletter platforms override
    if any(s.startswith("known-domain:") for s in detection.signals):
        return False

    return False


def detect_and_classify(headers: list[dict], from_header: str) -> DetectionResult | None:
    detection = detect_newsletter(headers, from_header)
    if not detection.is_newsletter:
        return None
    if is_personal_email(detection, headers):
        return None
    return detection


KNOWN_PLATFORM_LABELS = {
    "substack.com": "Substack",
    "beehiiv.com": "Beehiiv",
    "mailchimp.com": "Mailchimp",
    "convertkit.com": "ConvertKit",
    "buttondown.email": "Buttondown",
    "tinyletter.com": "TinyLetter",
    "ghost.io": "Ghost",
}


def platform_for_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    for known in KNOWN_NEWSLETTER_DOMAINS:
        if domain == known or domain.endswith("." + known):
            return KNOWN_PLATFORM_LABELS.get(known, known)
    return None
