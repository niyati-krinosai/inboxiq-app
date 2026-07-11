"""Discover personalized modes from a user's newsletters and article corpus."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CATEGORY_KEYWORDS
from app.models.article import Article
from app.models.newsletter import Newsletter

# Auto-theme buckets inferred from article titles (beyond static sidebar modes)
_THEME_KEYWORDS: dict[str, list[str]] = {
    "AI & Models": ["openai", "anthropic", "gpt", "claude", "llm", "gemini", "model", "ai"],
    "Startups & Funding": ["startup", "funding", "raised", "series", "venture", "ipo"],
    "Legal & Careers": ["law", "legal", "internship", "career", "job", "hiring"],
    "Developer & Open Source": ["github", "api", "sdk", "open source", "developer", "code"],
    "Product Launches": ["launch", "released", "announces", "introducing", "beta"],
}

_MIN_THEME_ARTICLES = 3
_MIN_NEWSLETTER_ISSUES = 1


async def discover_user_modes(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    tldr_only: bool = False,
) -> list[dict]:
    """Build stable, user-specific modes from subscriptions + reading patterns."""
    from app.services.mentor_profile import is_tldr_newsletter

    nl_result = await db.execute(
        select(Newsletter)
        .where(Newsletter.user_id == user_id)
        .order_by(Newsletter.issue_count.desc())
    )
    newsletters = list(nl_result.scalars().all())
    if tldr_only:
        newsletters = [nl for nl in newsletters if is_tldr_newsletter(nl)]

    modes: list[dict] = []

    # ── Per-newsletter modes (organize by source) ─────────────────────────────
    for nl in newsletters:
        if (nl.issue_count or 0) < _MIN_NEWSLETTER_ISSUES:
            continue
        article_count = nl.article_count or 0
        modes.append({
            "id": f"newsletter:{nl.id}",
            "label": _clean_label(nl.name or nl.sender_email),
            "kind": "newsletter",
            "description": f"{nl.issue_count} issues · {article_count} stories",
            "newsletter_id": str(nl.id),
        })

    # Krishna / TLDR-only desk: newsletter modes only (no auto themes)
    if tldr_only:
        return modes[:24]

    # ── Auto themes from recent article titles ────────────────────────────────
    title_result = await db.execute(
        select(Article.title)
        .where(Article.user_id == user_id)
        .order_by(Article.received_at.desc())
        .limit(400)
    )
    titles = [row[0] or "" for row in title_result.all()]

    static_labels = {c.lower() for c in CATEGORY_KEYWORDS}
    for theme, keywords in _THEME_KEYWORDS.items():
        if theme.lower() in static_labels:
            continue
        hits = sum(1 for t in titles if any(kw in (t or "").lower() for kw in keywords))
        if hits >= _MIN_THEME_ARTICLES:
            modes.append({
                "id": f"theme:{_slug(theme)}",
                "label": theme,
                "kind": "theme",
                "description": f"{hits} recent stories",
                "keywords": keywords,
            })

    return modes[:24]


def parse_mode_filter(category: str | None) -> tuple[str | None, str | None, list[str]]:
    """
    Parse sidebar selection into (static_mode, newsletter_id, theme_keywords).
    category examples: 'Fintech', 'newsletter:uuid', 'theme:ai-models'
    """
    if not category:
        return None, None, []

    if category.startswith("newsletter:"):
        return None, category.split(":", 1)[1], []

    if category.startswith("theme:"):
        slug = category.split(":", 1)[1]
        for theme, keywords in _THEME_KEYWORDS.items():
            if _slug(theme) == slug:
                return None, None, keywords
        return None, None, []

    return category, None, []


def _clean_label(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name[:48] if name else "Newsletter"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
