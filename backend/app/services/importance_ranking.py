"""Phase 16.4: Importance ranking — not just chronological."""

from app.config import get_settings
from app.constants import MAJOR_COMPANIES
from app.models.article import CanonicalEvent

settings = get_settings()


def compute_ranking_score(event: CanonicalEvent) -> float:
    """
    Importance = company weight + official source + mentions + funding
               + newsletter count + breaking/trending boost + base AI score
    """
    factors: dict[str, float] = {}
    score = 0.0

    # Base AI importance
    base = event.importance_score or 0.5
    factors["ai_score"] = base * 0.2
    score += factors["ai_score"]

    # Company weight
    companies = event.companies or []
    company_w = 0.0
    for c in companies:
        if isinstance(c, str):
            if c in settings.company_weights:
                company_w = max(company_w, settings.company_weights[c])
            elif c in MAJOR_COMPANIES:
                company_w = max(company_w, 0.8)
    factors["company_weight"] = company_w * 0.25
    score += factors["company_weight"]

    # Official source
    if event.official_link or event.enriched_content:
        factors["official_source"] = 0.2
        score += 0.2

    # Newsletter mentions (social proof across user's subscriptions)
    nl_count = event.newsletter_count or len(event.sources or [])
    mention_boost = min(nl_count * 0.04, 0.25)
    factors["newsletter_mentions"] = mention_boost
    score += mention_boost

    # Funding events
    funding = getattr(event, "funding", None) or []
    if funding:
        factors["funding"] = 0.15
        score += 0.15

    # Repository signals
    repos = event.repositories or []
    if repos:
        factors["repositories"] = 0.1
        score += 0.1

    # Confidence boost
    conf = event.confidence_score or event.confidence or 0.5
    factors["confidence"] = conf * 0.1
    score += factors["confidence"]

    # Breaking / trending
    if event.is_breaking:
        factors["breaking"] = 0.3
        score += 0.3
    elif event.is_trending:
        factors["trending"] = 0.15
        score += 0.15

    event.importance_factors = factors
    return min(score, 1.0)
