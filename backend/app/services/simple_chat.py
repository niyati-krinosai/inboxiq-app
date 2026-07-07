"""Intent-aware chat: responds to what you type, not just sidebar filters."""

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CATEGORIES, CATEGORY_KEYWORDS, TIMELINE_FILTERS, TIMELINE_LABELS
from app.models.article import Article
from app.models.newsletter import Newsletter
from app.services.article_summary import summarize_articles
from app.services.user_modes import parse_mode_filter

MAX_DIGEST_ITEMS = 20
MAX_SEARCH_ITEMS = 8
MAX_ELABORATE_ITEMS = 3
MIN_RELEVANCE_SCORE = 0.22

_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her", "was",
    "one", "our", "out", "day", "get", "has", "him", "his", "how", "its", "may",
    "new", "now", "old", "see", "two", "way", "who", "did", "let", "say", "she",
    "too", "use", "from", "that", "this", "with", "have", "will", "your", "what",
    "when", "where", "which", "about", "into", "than", "them", "then", "some",
    "would", "could", "should", "please", "tell", "give", "show", "send", "just",
    "also", "more", "news", "today", "week", "last", "been", "being", "does",
})

_STRONG_TOPIC_PATTERNS: dict[str, re.Pattern] = {
    cat: re.compile("|".join(re.escape(k) for k in kws), re.IGNORECASE)
    for cat, kws in CATEGORY_KEYWORDS.items()
}

_JUNK_PATTERNS = re.compile(
    r"(apply now|hackathon|unstop|lawctopus|call for papers|internship|"
    r"what do you think of our newsletter|view more competitions|cash prize|"
    r"you.?re receiving this email because|team unstop)",
    re.IGNORECASE,
)

_NEWSLETTER_ALIASES: dict[str, list[str]] = {
    "tldr": ["tldr", "tldr ai", "tldrnewsletter"],
    "rundown": ["rundown", "the rundown"],
    "bens bites": ["ben's bites", "bens bites", "bensbites"],
}


def _classify_intent(question: str) -> str:
    q = question.strip().lower()
    words = q.split()

    if re.match(r"^(hi|hello|hey|thanks|thank you|yo|sup|good morning|good evening)\b", q):
        if len(words) <= 5:
            return "greeting"
    if re.search(r"\b(help|how do i|how to use|what can you)\b", q):
        return "help"
    if re.search(
        r"\b(elaborate|explain more|tell me more|expand on|more about|more detail|"
        r"deep dive|details on|break down|walk me through)\b",
        q,
    ):
        return "elaborate"
    if re.search(
        r"\b(summarize|summary|digest|recap|roundup|what happened|updates?|"
        r"stories|highlights|catch me up|everything)\b",
        q,
    ):
        return "digest"
    if len(words) <= 2 and not re.search(r"\b(ai|gpt|api|ml)\b", q):
        return "vague"
    return "search"


def _query_tokens(question: str) -> set[str]:
    tokens = {
        t for t in re.findall(r"[a-z0-9]{3,}", question.lower())
        if t not in _STOPWORDS
    }
    return tokens


def _extract_story_subject(question: str) -> str:
    """Pull the story headline/topic from pasted newsletter text + ask phrasing."""
    q = question.strip()
    q = re.sub(r"^\d+\.\s*", "", q)
    for pat in (
        r"\b(tell me more about (this|the) (news|story|article).*)$",
        r"\b(elaborate on (this|the) (news|story).*)$",
        r"\b(more about (this|the) (news|story).*)$",
        r"\b(tell me more|elaborate|explain more)\s*$",
    ):
        q = re.sub(pat, "", q, flags=re.IGNORECASE).strip()
    return q


def _extract_focus_query(question: str) -> str:
    subject = _extract_story_subject(question)
    if subject and subject != question.strip():
        return subject
    for pat in (
        r"(?:elaborate|expand|explain|details?)\s+(?:on|about)\s+(.+)",
        r"(?:tell me )?more about\s+(.+)",
        r"(?:the\s+)?(.+?)\s+story",
        r"regarding\s+(.+)",
    ):
        m = re.search(pat, question, re.IGNORECASE)
        if m:
            focus = m.group(1).strip()
            if focus.lower() not in ("this news", "the news", "this story", "the story"):
                return focus
    return _extract_story_subject(question) or question


def _infer_timeline(question: str, timeline_filter: str | None) -> str:
    if timeline_filter and timeline_filter in TIMELINE_FILTERS:
        return timeline_filter
    q = question.lower()
    if any(p in q for p in ("today", "this morning", "24 hour", "past day")):
        return "24h"
    if any(p in q for p in ("yesterday", "2 day")):
        return "2d"
    if any(p in q for p in ("this week", "past week", "last week")):
        return "1w"
    if "month" in q:
        return "1m"
    return timeline_filter or "1w"


def _infer_newsletter_from_question(question: str) -> str | None:
    q = question.lower()
    if re.search(r"\bfrom\s+tldr\b|\btldr\b", q):
        return "tldr"
    if "rundown" in q:
        return "rundown"
    if "ben" in q and "bite" in q:
        return "bens bites"
    return None


def _infer_topics_from_question(question: str) -> list[str]:
    q = question.lower()
    matched = [cat for cat in CATEGORIES if cat.lower() in q]
    for cat, pattern in _STRONG_TOPIC_PATTERNS.items():
        if cat not in matched and pattern.search(q):
            matched.append(cat)
    return matched


def _topic_matches(article: Article, topics: list[str], theme_keywords: list[str]) -> bool:
    blob = f"{article.title} {article.content_text or ''} {' '.join(article.categories or [])}".lower()
    for topic in topics:
        pattern = _STRONG_TOPIC_PATTERNS.get(topic)
        if pattern and pattern.search(blob):
            return True
        if topic.lower() in blob:
            return True
    for kw in theme_keywords:
        if kw.lower() in blob:
            return True
    return False


def _is_junk(article: Article) -> bool:
    return bool(_JUNK_PATTERNS.search(f"{article.title} {article.content_text or ''}"))


def _article_link(article: Article) -> str | None:
    return article.url or article.official_link or article.newsletter_link


def _title_match_ratio(title: str, q_tokens: set[str]) -> float:
    if not q_tokens or not title:
        return 0.0
    title_tokens = set(re.findall(r"[a-z0-9]{3,}", title.lower()))
    if not title_tokens:
        return 0.0
    hits = sum(1 for t in q_tokens if t in title_tokens or t in title.lower())
    return hits / len(q_tokens)


def _title_phrase_boost(title: str, subject: str) -> float:
    """Strong match when the user pastes or names a specific headline (any story)."""
    if not title or not subject or len(subject) < 12:
        return 0.0
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    subj = norm(subject)
    tit = norm(title)
    if not subj or not tit:
        return 0.0
    if subj in tit or tit in subj:
        return 1.0
    subj_words = [w for w in subj.split() if len(w) >= 4]
    if len(subj_words) >= 3:
        hits = sum(1 for w in subj_words if w in tit)
        if hits / len(subj_words) >= 0.6:
            return 0.85
    return 0.0


def _score_article(
    article: Article,
    question: str,
    q_tokens: set[str],
    static_mode: str | None,
    theme_keywords: list[str],
    intent: str,
    story_subject: str = "",
) -> float:
    blob = f"{article.title} {article.content_text or ''} {' '.join(article.categories or [])}".lower()
    title_blob = (article.title or "").lower()

    if not q_tokens:
        overlap = 0.0
    else:
        overlap = sum(1 for t in q_tokens if t in blob) / len(q_tokens)
        title_hits = sum(1 for t in q_tokens if t in title_blob)
        overlap += title_hits * 0.2

    title_ratio = _title_match_ratio(article.title or "", q_tokens)
    phrase_boost = _title_phrase_boost(article.title or "", story_subject or question)
    title_boost = max(title_ratio * (0.8 if intent == "elaborate" else 0.35), phrase_boost)

    mode_boost = 0.0
    if static_mode and _topic_matches(article, [static_mode], []):
        weight = 0.08 if intent == "elaborate" else (0.2 if intent != "digest" else 0.35)
        mode_boost += weight
    if theme_keywords and _topic_matches(article, [], theme_keywords):
        weight = 0.1 if intent == "elaborate" else 0.3
        mode_boost += weight

    recency = 0.0
    ts = article.received_at or article.published_at
    if ts:
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        recency = max(0, 1 - age_h / (24 * 7)) * (0.05 if intent == "elaborate" else 0.15)

    link_boost = 0.1 if _article_link(article) else 0.0
    junk_penalty = -3.0 if _is_junk(article) else 0.0

    if intent == "elaborate":
        overlap *= 1.5

    return overlap * 0.55 + title_boost + mode_boost + recency + link_boost + junk_penalty


def _period_label(timeline: str) -> str:
    return TIMELINE_LABELS.get(timeline, f"the last {TIMELINE_FILTERS.get(timeline, 7)} day(s)")


def _conversational_response(intent: str, question: str) -> dict:
    if intent == "greeting":
        return {
            "headline": "Hello!",
            "brief_summary": (
                "I search your Gmail newsletters based on what you ask — not just the sidebar filters.\n\n"
                "Try:\n"
                "• \"Summarize AI tools launched this week\"\n"
                "• \"Elaborate on the OpenAI GPT story\"\n"
                "• \"What did TLDR cover about agents?\""
            ),
            "items": [],
            "sources": [],
            "related_news": [],
        }
    if intent == "help":
        return {
            "headline": "How to use InboxIQ Ask",
            "brief_summary": (
                "Pick a mode and timeline as optional filters, then ask naturally.\n\n"
                "• Digest — \"Summarize fintech news this week\"\n"
                "• Specific — \"Tell me about the Claude release\"\n"
                "• Elaborate — \"Elaborate on the first story about GPUs\"\n\n"
                "Modes narrow results; your question controls what comes back."
            ),
            "items": [],
            "sources": [],
            "related_news": [],
        }
    return {
        "headline": "What would you like to know?",
        "brief_summary": (
            f"\"{question}\" is a bit short for me to search your newsletters.\n\n"
            "Try asking about a topic, newsletter, or story — e.g. "
            "\"Elaborate on the Anthropic story\" or \"TLDR digest this week\"."
        ),
        "items": [],
        "sources": [],
        "related_news": [],
    }


def _build_response(
    intent: str,
    question: str,
    items: list[dict],
    mode_label: str,
    period: str,
) -> dict:
    if not items:
        return {
            "headline": "No matching stories",
            "brief_summary": (
                f"Nothing in your newsletters matched \"{question}\" for {period}.\n"
                "Try different wording, a wider timeline, or another mode."
            ),
            "why_it_matters": "",
            "items": [],
            "sources": [],
            "related_news": [],
        }

    if intent == "elaborate":
        headline = f"Deep dive — {items[0]['title'][:80]}"
        brief = f"Here's a detailed look at the story you asked about ({period})."
    elif intent == "search":
        headline = f"Results for: {question[:80]}"
        brief = f"Found {len(items)} stor{'y' if len(items) == 1 else 'ies'} from {period}."
    else:
        headline = f"{mode_label} — {period}"
        brief = f"{len(items)} stories from your {mode_label} newsletters ({period})."

    return {
        "headline": headline,
        "brief_summary": brief,
        "why_it_matters": "",
        "items": items,
        "sources": [{"newsletter": i["newsletter"], "url": i["url"]} for i in items],
        "related_news": [i["title"] for i in items[1:6]],
    }


async def simple_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    category_filter: str | None = None,
    timeline_filter: str | None = None,
) -> dict:
    intent = _classify_intent(question)
    if intent in ("greeting", "help", "vague"):
        return {**_conversational_response(intent, question), "why_it_matters": ""}

    timeline = _infer_timeline(question, timeline_filter)
    if timeline not in TIMELINE_FILTERS:
        timeline = "1w"
    period = _period_label(timeline)
    cutoff = datetime.now(timezone.utc) - timedelta(days=TIMELINE_FILTERS[timeline])

    static_mode, newsletter_id, theme_keywords = parse_mode_filter(category_filter)
    nl_from_question = _infer_newsletter_from_question(question)

    story_subject = _extract_story_subject(question)
    search_question = _extract_focus_query(question) if intent == "elaborate" else question
    q_tokens = _query_tokens(search_question)

    # Digest with a mode selected and vague question → use mode as primary filter
    topics_from_q = _infer_topics_from_question(question)
    strict_mode = (
        intent == "digest"
        and (static_mode or theme_keywords)
        and len(q_tokens) <= 4
    )

    mode_label = static_mode or category_filter or "Your newsletters"
    if category_filter and category_filter.startswith("newsletter:"):
        nl_row = await db.get(Newsletter, uuid.UUID(newsletter_id)) if newsletter_id else None
        if nl_row:
            mode_label = nl_row.name

    items = await _fetch_articles(
        db=db,
        user_id=user_id,
        question=search_question,
        story_subject=story_subject,
        q_tokens=q_tokens,
        cutoff=cutoff,
        intent=intent,
        static_mode=static_mode if strict_mode else None,
        theme_keywords=theme_keywords if strict_mode else theme_keywords,
        topics_from_q=topics_from_q,
        newsletter_id=newsletter_id,
        nl_from_question=nl_from_question,
        soft_mode=static_mode if not strict_mode else None,
        soft_theme=theme_keywords if not strict_mode else [],
    )

    return _build_response(intent, question, items, mode_label, period)


async def _fetch_articles(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    story_subject: str,
    q_tokens: set[str],
    cutoff: datetime,
    intent: str,
    static_mode: str | None,
    theme_keywords: list[str],
    topics_from_q: list[str],
    newsletter_id: str | None,
    nl_from_question: str | None,
    soft_mode: str | None,
    soft_theme: list[str],
) -> list[dict]:
    stmt = (
        select(Article, Newsletter.name.label("newsletter_name"), Newsletter.id.label("nl_id"))
        .join(Newsletter, Newsletter.id == Article.newsletter_id)
        .where(Article.user_id == user_id, Article.received_at >= cutoff)
    )
    result = await db.execute(stmt.order_by(Article.received_at.desc()).limit(500))
    rows = list(result.all())

    if newsletter_id:
        try:
            nid = uuid.UUID(newsletter_id)
            rows = [r for r in rows if r.nl_id == nid]
        except ValueError:
            pass

    if nl_from_question:
        rows = [
            r for r in rows
            if any(a in (r.newsletter_name or "").lower() for a in _NEWSLETTER_ALIASES.get(nl_from_question, [nl_from_question]))
        ]

    rows = [(a, n, i) for a, n, i in rows if not _is_junk(a)]

    # Strict filters (digest + mode)
    if static_mode or theme_keywords:
        filtered = [
            r for r in rows
            if _topic_matches(r[0], [static_mode] if static_mode else [], theme_keywords)
        ]
        if filtered:
            rows = filtered

    if topics_from_q and intent == "search":
        filtered = [r for r in rows if _topic_matches(r[0], topics_from_q, [])]
        if filtered:
            rows = filtered

    ranked = sorted(
        rows,
        key=lambda r: _score_article(
            r[0], question, q_tokens,
            soft_mode or static_mode, soft_theme or theme_keywords, intent,
            story_subject,
        ),
        reverse=True,
    )

    scores = [
        _score_article(r[0], question, q_tokens, soft_mode or static_mode, soft_theme or theme_keywords, intent, story_subject)
        for r in ranked
    ]

    if intent == "elaborate":
        max_items = 1
        min_score = 0.45 if len(q_tokens) >= 4 else 0.3
        long_summary = True
    elif intent == "digest":
        max_items = MAX_DIGEST_ITEMS
        min_score = 0.08 if (static_mode or theme_keywords) else MIN_RELEVANCE_SCORE
        long_summary = False
    else:
        max_items = MAX_SEARCH_ITEMS
        min_score = MIN_RELEVANCE_SCORE
        long_summary = False

    top = [r for r, s in zip(ranked, scores) if s >= min_score][:max_items]

    # Never dump all articles for weak queries
    if not top and intent == "digest" and (static_mode or theme_keywords):
        top = ranked[:max_items]

    article_rows = [(article, newsletter_name) for article, newsletter_name, _ in top]
    long_flags = [long_summary] * len(article_rows)
    summaries = await summarize_articles(
        [a for a, _ in article_rows],
        long_flags=long_flags,
    )

    items = []
    for (article, newsletter_name), summary in zip(article_rows, summaries):
        items.append({
            "title": article.title,
            "summary": summary,
            "url": _article_link(article),
            "newsletter": newsletter_name,
            "published_at": (article.received_at or article.published_at).isoformat()
            if (article.received_at or article.published_at) else None,
        })
    return items
