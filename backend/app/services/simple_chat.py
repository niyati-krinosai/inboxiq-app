"""Intent-aware chat: responds to what you type, not just sidebar filters."""

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CATEGORIES, CATEGORY_KEYWORDS, TIMELINE_FILTERS, TIMELINE_LABELS
from app.models.article import Article
from app.models.newsletter import Newsletter
from app.services.article_qa import answer_article_question
from app.services.article_summary import summarize_articles
from app.services.chat_memory import (
    clear_active_article,
    get_active_article,
    get_conversation_turns,
    get_or_create_session,
    should_answer_about_active_article,
    update_session_memory,
)
from app.services.user_modes import parse_mode_filter

# Elaborate still deep-dives one story; digests/search return the full timeline set.
# Above this count, use stored/heuristic summaries (LLM would time out / cost too much).
LLM_SUMMARY_CAP = 12

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


_GENERIC_NEWS_TOKENS = frozenset({
    "model", "protocol", "launched", "introduced", "released", "announced",
    "tools", "server", "capabilities", "applications", "features", "updates",
    "integration", "integrations", "platform", "company", "product", "products",
    "service", "services", "developer", "developers", "engineering", "research",
})

_DETAIL_ASK_SUFFIX = re.compile(
    r"\b("
    r"tell me (?:more |detailed |the )?(?:news|details?|story)(?:\s+on\s+this)?|"
    r"give me (?:more )?details?(?:\s+on\s+this)?|"
    r"(?:more |full )?details?(?:\s+on)?\s+(?:this|that)(?:\s+news|\s+story)?|"
    r"detailed news on this|explain this|expand on this"
    r")\s*$",
    re.IGNORECASE,
)


def _is_pasted_story_detail_request(question: str) -> bool:
    q = question.strip()
    return len(q) >= 80 and bool(_DETAIL_ASK_SUFFIX.search(q))


def _classify_intent(question: str) -> str:
    q = question.strip().lower()
    words = q.split()

    if re.match(r"^(hi|hello|hey|thanks|thank you|yo|sup|good morning|good evening)\b", q):
        if len(words) <= 5:
            return "greeting"
    if re.search(r"\b(help|how do i|how to use|what can you)\b", q):
        return "help"
    if _is_pasted_story_detail_request(question):
        return "elaborate"
    if re.search(
        r"\b(elaborate|explain more|tell me more|tell me (?:the )?detail|tell me detailed|"
        r"detailed news|more detail|more details|in detail|full details?|"
        r"expand on|more about|deep dive|details on|break down|walk me through)\b",
        q,
    ):
        return "elaborate"
    if re.search(
        r"\b(summarize|summary|digest|recap|roundup|what happened|updates?|"
        r"stories|highlights|catch me up|everything|all (the )?news|the news|"
        r"tell me (the )?news|news in|news about)\b",
        q,
    ):
        return "digest"
    if len(words) <= 2 and not re.search(r"\b(ai|gpt|api|ml)\b", q):
        return "vague"
    return "search"


def _query_tokens(question: str, *, distinctive_only: bool = False) -> set[str]:
    tokens = {
        t for t in re.findall(r"[a-z0-9]{3,}", question.lower())
        if t not in _STOPWORDS
    }
    if distinctive_only:
        tokens = {t for t in tokens if t not in _GENERIC_NEWS_TOKENS}
    return tokens


def _extract_story_subject(question: str) -> str:
    """Pull the story headline/topic from pasted newsletter text + ask phrasing."""
    q = question.strip()
    q = re.sub(r"^\d+\.\s*", "", q)
    q = _DETAIL_ASK_SUFFIX.sub("", q).strip()
    for pat in (
        r"\b(tell me more about (this|the) (news|story|article).*)$",
        r"\b(elaborate on (this|the) (news|story).*)$",
        r"\b(more about (this|the) (news|story).*)$",
        r"\b(tell me more|elaborate|explain more)\s*$",
    ):
        q = re.sub(pat, "", q, flags=re.IGNORECASE).strip()
    return q


def _extract_story_headline(subject: str) -> str:
    """Short headline anchor from pasted newsletter text (avoids generic body-token matches)."""
    if not subject:
        return ""
    s = subject.strip()
    if len(s) <= 100:
        return s
    for pat in (
        r"^(.+?,\s+which\b)",
        r"^(.+?,\s+enabling\b)",
        r"^(.+?,\s+allowing\b)",
        r"^(.+?\.)",
    ):
        m = re.match(pat, s, re.IGNORECASE)
        if m and len(m.group(1)) >= 20:
            return m.group(1).rstrip(",").strip()
    return " ".join(s.split()[:14])


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


def _headline_sequence_boost(title: str, headline: str) -> float:
    """Reward consecutive headline words appearing in the article title."""
    if not title or not headline:
        return 0.0
    words = [
        w for w in re.findall(r"[a-z0-9]+", headline.lower())
        if len(w) >= 2 and w not in _STOPWORDS and w not in _GENERIC_NEWS_TOKENS
    ]
    if len(words) < 3:
        return 0.0
    title_norm = re.sub(r"[^a-z0-9]+", " ", title.lower())
    best = 0
    for i in range(len(words)):
        for j in range(i + 3, min(i + 8, len(words)) + 1):
            phrase = " ".join(words[i:j])
            if phrase in title_norm:
                best = max(best, j - i)
    if best >= 4:
        return 1.0
    if best >= 3:
        return 0.75
    return 0.0


def _title_phrase_boost(title: str, subject: str) -> float:
    """Strong match when the user pastes or names a specific headline (any story)."""
    if not title or not subject:
        return 0.0
    headline = _extract_story_headline(subject) if len(subject) > 100 else subject
    if len(headline) < 12:
        return 0.0
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    subj = norm(headline)
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
    return _headline_sequence_boost(title, headline)


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
    phrase_subject = story_subject or question
    phrase_boost = _title_phrase_boost(article.title or "", phrase_subject)
    seq_boost = _headline_sequence_boost(
        article.title or "",
        _extract_story_headline(phrase_subject) if len(phrase_subject) > 80 else phrase_subject,
    )
    title_boost = max(
        title_ratio * (0.8 if intent == "elaborate" else 0.35),
        phrase_boost,
        seq_boost * (1.0 if intent == "elaborate" else 0.5),
    )

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
        brief = (
            f"All {len(items)} matching stor{'y' if len(items) == 1 else 'ies'} "
            f"from {period} (complete list, not a top-N)."
        )

    return {
        "headline": headline,
        "brief_summary": brief,
        "why_it_matters": "",
        "items": items,
        "sources": [{"newsletter": i["newsletter"], "url": i["url"]} for i in items],
        "related_news": [],
    }


async def simple_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    category_filter: str | None = None,
    timeline_filter: str | None = None,
    session_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
    clear_article_context: bool = False,
) -> dict:
    session = await get_or_create_session(db, user_id, session_id)

    if clear_article_context:
        await clear_active_article(db, session)
        return {
            "headline": "",
            "brief_summary": "",
            "why_it_matters": "",
            "items": [],
            "sources": [],
            "related_news": [],
            "session_id": str(session.id),
            "active_article": None,
        }

    if should_answer_about_active_article(question, session, pinned_article_id=article_id):
        followup = await _answer_about_article(
            db, user_id, question, session, pinned_article_id=article_id,
        )
        if followup:
            await update_session_memory(
                db, session, question, followup, active_article=followup.get("_active_article"),
            )
            followup["session_id"] = str(session.id)
            followup["active_article"] = followup.get("_active_article")
            followup.pop("_active_article", None)
            return followup

    intent = _classify_intent(question)
    topics_from_q = _infer_topics_from_question(question)
    # Topic / mode listing questions should dump the full timeline set, not a short search hit list.
    if intent == "search" and (topics_from_q or category_filter):
        intent = "digest"
    if intent in ("greeting", "help", "vague"):
        result = {**_conversational_response(intent, question), "why_it_matters": ""}
        result["session_id"] = str(session.id)
        await update_session_memory(db, session, question, result, active_article=None)
        return result

    timeline = _infer_timeline(question, timeline_filter)
    if timeline not in TIMELINE_FILTERS:
        timeline = "1w"
    period = _period_label(timeline)
    cutoff = datetime.now(timezone.utc) - timedelta(days=TIMELINE_FILTERS[timeline])

    static_mode, newsletter_id, theme_keywords = parse_mode_filter(category_filter)
    nl_from_question = _infer_newsletter_from_question(question)

    story_subject = _extract_story_subject(question)
    story_headline = _extract_story_headline(story_subject)

    if intent == "elaborate":
        search_question = _extract_focus_query(question)
        token_source = story_headline or search_question
        q_tokens = _query_tokens(token_source, distinctive_only=True) or _query_tokens(token_source)
        if story_headline:
            story_subject = story_headline
    else:
        search_question = question
        q_tokens = _query_tokens(search_question)

    mode_label = static_mode or category_filter or "Your newsletters"
    if category_filter and category_filter.startswith("newsletter:"):
        nl_row = await db.get(Newsletter, uuid.UUID(newsletter_id)) if newsletter_id else None
        if nl_row:
            mode_label = nl_row.name
    elif topics_from_q:
        mode_label = topics_from_q[0]

    items = await _fetch_articles(
        db=db,
        user_id=user_id,
        question=search_question,
        story_subject=story_subject,
        q_tokens=q_tokens,
        cutoff=cutoff,
        intent=intent,
        static_mode=static_mode,
        theme_keywords=theme_keywords,
        topics_from_q=topics_from_q,
        newsletter_id=newsletter_id,
        nl_from_question=nl_from_question,
        soft_mode=None,
        soft_theme=[],
    )

    result = _build_response(intent, question, items, mode_label, period)
    active_article = None
    if len(items) == 1 and items[0].get("article_id"):
        active_article = {
            "article_id": items[0]["article_id"],
            "title": items[0]["title"],
            "url": items[0].get("url"),
            "newsletter": items[0].get("newsletter"),
        }
    result["session_id"] = str(session.id)
    if active_article:
        result["active_article"] = active_article
    await update_session_memory(db, session, question, result, active_article=active_article)
    return result


async def _answer_about_article(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    session,
    *,
    pinned_article_id: uuid.UUID | None = None,
) -> dict | None:
    if pinned_article_id:
        article_id = pinned_article_id
        newsletter_name = "Newsletter"
        active_meta = get_active_article(session) or {}
    else:
        active = get_active_article(session)
        if not active or not active.get("article_id"):
            return None
        try:
            article_id = uuid.UUID(active["article_id"])
        except ValueError:
            return None
        newsletter_name = active.get("newsletter") or "Newsletter"
        active_meta = active

    article = await db.get(Article, article_id)
    if not article or article.user_id != user_id:
        return None

    if pinned_article_id:
        nl_row = await db.get(Newsletter, article.newsletter_id)
        if nl_row:
            newsletter_name = nl_row.name

    q_lower = question.strip().lower()
    wants_deep_dive = bool(re.search(
        r"\b(detail|elaborate|explain|tell me more|deep dive|full account|in depth)\b",
        q_lower,
    ))

    if wants_deep_dive:
        summaries = await summarize_articles([article], depths=["elaborate"])
        answer = summaries[0]
    else:
        answer = await answer_article_question(
            article,
            newsletter_name,
            question,
            get_conversation_turns(session),
        )

    url = _article_link(article) or active_meta.get("url")
    item = {
        "article_id": str(article.id),
        "title": article.title,
        "summary": answer,
        "url": url,
        "newsletter": newsletter_name,
        "published_at": (article.received_at or article.published_at).isoformat()
        if (article.received_at or article.published_at) else None,
    }
    active_article = {
        "article_id": str(article.id),
        "title": article.title,
        "url": url,
        "newsletter": newsletter_name,
    }
    return {
        "headline": f"About — {article.title[:80]}",
        "brief_summary": f"Answering about \"{article.title[:60]}\" from {newsletter_name}.",
        "why_it_matters": "",
        "items": [item],
        "sources": [{"newsletter": newsletter_name, "url": url}],
        "related_news": [],
        "_active_article": active_article,
    }


async def _answer_followup(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    session,
) -> dict | None:
    return await _answer_about_article(db, user_id, question, session)


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

    # Krishna mentor desk: only TLDR products
    from app.models.user import User as UserModel
    from app.services.mentor_profile import is_krishna_user, is_tldr_newsletter

    user_row = await db.get(UserModel, user_id)
    if user_row and is_krishna_user(user_row):
        tldr_ids = [
            nl.id
            for nl in (
                await db.execute(select(Newsletter).where(Newsletter.user_id == user_id))
            ).scalars()
            if is_tldr_newsletter(nl)
        ]
        if tldr_ids:
            stmt = stmt.where(Article.newsletter_id.in_(tldr_ids))
        else:
            return []

    # Full timeline dump for digests/search — no artificial row cap.
    # Elaborate can stay bounded while ranking a candidate pool.
    if intent == "elaborate":
        result = await db.execute(stmt.order_by(Article.received_at.desc()).limit(2000))
    else:
        result = await db.execute(stmt.order_by(Article.received_at.desc()))
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

    # Hard topic / mode filters — keep every match in the selected timeline
    topic_filters = [t for t in ([static_mode] if static_mode else []) + list(topics_from_q or []) if t]
    if topic_filters or theme_keywords:
        filtered = [
            r for r in rows
            if _topic_matches(r[0], topic_filters, theme_keywords or [])
        ]
        # Only apply if we found matches; otherwise leave rows (except when mode/topic was explicit)
        if filtered:
            rows = filtered
        elif topic_filters or theme_keywords:
            rows = []

    if intent == "elaborate":
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
            _score_article(
                r[0], question, q_tokens,
                soft_mode or static_mode, soft_theme or theme_keywords, intent,
                story_subject,
            )
            for r in ranked
        ]
        min_score = 0.45 if len(q_tokens) >= 4 else 0.3
        top = [r for r, s in zip(ranked, scores) if s >= min_score][:1]
        if not top and ranked:
            top = ranked[:1]
    else:
        # Complete list for the timeline window — newest first, no top-N trim
        top = sorted(
            rows,
            key=lambda r: r[0].received_at or r[0].published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    article_rows = [(article, newsletter_name) for article, newsletter_name, _ in top]

    from app.services.article_summary import heuristic_article_summary

    if intent == "elaborate":
        summaries = await summarize_articles(
            [a for a, _ in article_rows],
            depths=["elaborate"] * len(article_rows),
        )
    elif len(article_rows) <= LLM_SUMMARY_CAP:
        summaries = await summarize_articles(
            [a for a, _ in article_rows],
            depths=["digest"] * len(article_rows),
        )
    else:
        # Large complete dumps: use stored/heuristic summaries so every story is included
        summaries = [heuristic_article_summary(a, long=False) for a, _ in article_rows]

    items = []
    for (article, newsletter_name), summary in zip(article_rows, summaries):
        items.append({
            "article_id": str(article.id),
            "title": article.title,
            "summary": summary,
            "url": _article_link(article),
            "newsletter": newsletter_name,
            "published_at": (article.received_at or article.published_at).isoformat()
            if (article.received_at or article.published_at) else None,
        })
    return items
