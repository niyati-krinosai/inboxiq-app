"""Phase 16.2: Multi-source confidence scoring."""

from app.constants import SOURCE_WEIGHTS, VERIFICATION_LEVELS
from app.models.article import CanonicalEvent, EventSource


def compute_event_confidence(event: CanonicalEvent, sources: list[EventSource]) -> None:
    """Compute confidence_score and verification_level from source weights."""
    if not sources:
        event.confidence_score = 0.3
        event.verification_level = "emerging"
        return

    weights = []
    has_official = False

    for s in sources:
        st = s.source_type or "newsletter"
        w = s.source_weight or SOURCE_WEIGHTS.get(st, SOURCE_WEIGHTS["newsletter"])
        weights.append(w)
        if st in ("official_blog", "documentation", "github_release"):
            has_official = True

    # Also factor in enriched official content on the event itself
    if event.enriched_content or event.official_link:
        weights.append(SOURCE_WEIGHTS["official_blog"])
        has_official = True

    avg_weight = sum(weights) / len(weights)
    newsletter_boost = min(len(sources) * 0.05, 0.25)
    event.confidence_score = min(avg_weight + newsletter_boost, 1.0)
    event.confidence = event.confidence_score

    n = len(sources)
    if has_official and n >= 2 and event.confidence_score >= 0.85:
        event.verification_level = "verified"
    elif n >= 3 or event.confidence_score >= 0.75:
        event.verification_level = "highly_likely"
    elif n >= 2:
        event.verification_level = "reported"
    else:
        event.verification_level = "emerging"


def verification_label(level: str | None) -> str:
    labels = {
        "verified": "Verified",
        "highly_likely": "Highly Likely",
        "reported": "Reported by newsletters",
        "emerging": "Emerging",
    }
    return labels.get(level or "", "Emerging")
