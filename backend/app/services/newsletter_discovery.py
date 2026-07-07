import json
import re
from dataclasses import dataclass, field
from email.utils import parseaddr

from app.constants import KNOWN_NEWSLETTER_DOMAINS, NEWSLETTER_SENDER_PREFIXES


@dataclass
class DetectionResult:
    is_newsletter: bool
    confidence: float
    signals: list[str] = field(default_factory=list)
    sender_email: str = ""
    sender_name: str = ""
    domain: str = ""


def _extract_domain(email: str) -> str:
    match = re.search(r"@([\w.-]+)", email.lower())
    return match.group(1) if match else ""


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def detect_newsletter(headers: list[dict], from_header: str) -> DetectionResult:
    """Multi-heuristic newsletter detection from Gmail message headers."""
    signals: list[str] = []
    score = 0.0

    sender_name, sender_email = parseaddr(from_header)
    sender_email = sender_email.lower().strip()
    domain = _extract_domain(sender_email)

    # List-Unsubscribe header (strong signal)
    list_unsub = _get_header(headers, "List-Unsubscribe")
    if list_unsub:
        signals.append("list-unsubscribe")
        score += 0.35

    # List-ID header
    list_id = _get_header(headers, "List-Id")
    if list_id:
        signals.append("list-id")
        score += 0.25

    # Precedence: bulk
    precedence = _get_header(headers, "Precedence").lower()
    if precedence == "bulk":
        signals.append("precedence-bulk")
        score += 0.20

    # Auto-Submitted
    auto_submitted = _get_header(headers, "Auto-Submitted").lower()
    if auto_submitted and auto_submitted != "no":
        signals.append("auto-submitted")
        score += 0.15

    # X-Mailer bulk indicators
    for header_name in ("X-Mailer", "X-Campaign", "X-Mailgun-Tag", "X-SG-EID"):
        if _get_header(headers, header_name):
            signals.append(f"bulk-header:{header_name.lower()}")
            score += 0.10
            break

    # Sender pattern matching
    local_part = sender_email.split("@")[0] + "@" if "@" in sender_email else ""
    for prefix in NEWSLETTER_SENDER_PREFIXES:
        if sender_email.startswith(prefix) or local_part.startswith(prefix.split("@")[0] + "@"):
            signals.append(f"sender-pattern:{prefix}")
            score += 0.15
            break

    # Known newsletter domains
    base_domain = domain
    for known in KNOWN_NEWSLETTER_DOMAINS:
        if domain == known or domain.endswith("." + known):
            signals.append(f"known-domain:{known}")
            score += 0.30
            base_domain = known
            break

    # Feedback-ID (Gmail bulk indicator)
    feedback_id = _get_header(headers, "Feedback-ID")
    if feedback_id:
        signals.append("feedback-id")
        score += 0.10

    confidence = min(score, 1.0)
    is_newsletter = confidence >= 0.35

    return DetectionResult(
        is_newsletter=is_newsletter,
        confidence=confidence,
        signals=signals,
        sender_email=sender_email,
        sender_name=sender_name,
        domain=base_domain or domain,
    )


def detection_signals_to_json(signals: list[str]) -> str:
    return json.dumps(signals)
