"""Readable article summaries for chat — LLM when available, cleaned prose otherwise."""

import json
import re

from app.config import get_settings
from app.core.logging import get_logger
from app.models.article import Article
from app.providers.openai_client import create_openai_client

settings = get_settings()
log = get_logger(__name__)
client = create_openai_client()

DIGEST_SENTENCES = 6
ELABORATE_SENTENCES = 10
DIGEST_MAX_CHARS = 900
ELABORATE_MAX_CHARS = 1400
LLM_BATCH_SIZE = 8

_JUNK_LINE = re.compile(
    r"(unsubscribe|view in browser|read online|sponsor|advertisement|"
    r"you.?re receiving this|click here|apply now|^\s*https?://\S+\s*$|"
    r"^\s*[\*\-•]\s*$|^\d+[\.\)]\s*$)",
    re.IGNORECASE,
)
_URL_ONLY = re.compile(r"^https?://\S+$", re.IGNORECASE)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_title_prefix(text: str, title: str) -> str:
    if not text or not title:
        return text.strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and _normalize_whitespace(lines[0]).lower() == _normalize_whitespace(title).lower():
        return "\n".join(lines[1:]).strip()
    norm_text = _normalize_whitespace(text).lower()
    norm_title = _normalize_whitespace(title).lower()
    if norm_text.startswith(norm_title):
        return _normalize_whitespace(text[len(norm_title) :]).strip()
    return text.strip()


def _clean_content(text: str) -> str:
    if not text:
        return ""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"https?://\S+", "", line).strip()
        line = re.sub(
            r"\b(view in browser|read online|unsubscribe|sponsored by|click here)\b.*",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()
        if not line or len(line) < 12:
            continue
        if _URL_ONLY.match(line) or _JUNK_LINE.search(line):
            continue
        lines.append(line)
    if lines:
        return _normalize_whitespace(" ".join(lines))

    # Fallback: sentence-level cleanup when newsletter text is one long line.
    fallback = re.sub(r"https?://\S+", "", text)
    fallback = re.sub(
        r"\b(view in browser|read online|unsubscribe|sponsored by|click here)\b[^.!?]*[.!?]?",
        "",
        fallback,
        flags=re.IGNORECASE,
    )
    return _normalize_whitespace(fallback.strip())


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    sentences = []
    for part in parts:
        s = part.strip()
        if len(s) < 25:
            continue
        if _JUNK_LINE.search(s):
            continue
        if s.count("http") >= 2:
            continue
        sentences.append(s)
    return sentences


def _compose_from_fields(article: Article) -> str | None:
    chunks: list[str] = []
    meta = article.metadata_json or {}
    for field in (
        meta.get("summary"),
        article.short_summary,
        article.why_it_matters,
        article.business_impact,
        article.technical_impact,
        article.developer_takeaway,
    ):
        if not field:
            continue
        text = _normalize_whitespace(str(field))
        if len(text) < 40 or text in chunks:
            continue
        if _looks_like_raw_snippet(text, article.title or ""):
            continue
        chunks.append(text)
    if not chunks:
        return None
    return " ".join(chunks)


def _looks_like_raw_snippet(text: str, title: str) -> bool:
    """Detect summaries that are just truncated newsletter paste."""
    title_norm = _normalize_whitespace(title).lower()
    text_norm = _normalize_whitespace(text).lower()
    if title_norm and text_norm == title_norm:
        return True
    if title_norm and text_norm.startswith(title_norm) and len(text_norm) < len(title_norm) + 40:
        return True
    if len(text) < 80:
        return False
    if text.count("\n") > 2:
        return True
    if re.search(r"\b(read more|view in browser|sponsored by)\b", text, re.I):
        return True
    return False


def heuristic_article_summary(article: Article, *, long: bool = False) -> str:
    composed = _compose_from_fields(article)
    if composed and not _looks_like_raw_snippet(composed, article.title or ""):
        limit = ELABORATE_MAX_CHARS if long else DIGEST_MAX_CHARS
        return composed[:limit] + ("…" if len(composed) > limit else "")

    raw = _strip_title_prefix(article.content_text or "", article.title or "")
    cleaned = _clean_content(raw)
    if not cleaned:
        return "No summary available for this story."

    sentences = _split_sentences(cleaned)
    if not sentences:
        sentences = [cleaned]

    target = ELABORATE_SENTENCES if long else DIGEST_SENTENCES
    summary = " ".join(sentences[:target]).strip()
    limit = ELABORATE_MAX_CHARS if long else DIGEST_MAX_CHARS

    if len(summary) < 120 and len(cleaned) > len(summary):
        summary = cleaned[:limit]

    return summary[:limit] + ("…" if len(cleaned) > limit else "")


async def summarize_articles(articles: list[Article], *, long_flags: list[bool]) -> list[str]:
    if not articles:
        return []
    if len(long_flags) != len(articles):
        long_flags = [False] * len(articles)

    if client and settings.openai_api_key:
        try:
            return await _summarize_with_llm(articles, long_flags)
        except Exception as exc:
            log.warning("article_summary_llm_failed", error=str(exc))

    return [heuristic_article_summary(a, long=flag) for a, flag in zip(articles, long_flags)]


async def _summarize_with_llm(articles: list[Article], long_flags: list[bool]) -> list[str]:
    summaries: list[str | None] = [None] * len(articles)

    for start in range(0, len(articles), LLM_BATCH_SIZE):
        batch_articles = articles[start : start + LLM_BATCH_SIZE]
        batch_flags = long_flags[start : start + LLM_BATCH_SIZE]
        batch_summaries = await _llm_batch(batch_articles, batch_flags)
        for offset, summary in enumerate(batch_summaries):
            summaries[start + offset] = summary

    return [
        s if s else heuristic_article_summary(a, long=flag)
        for s, a, flag in zip(summaries, articles, long_flags)
    ]


async def _llm_batch(articles: list[Article], long_flags: list[bool]) -> list[str]:
    stories = []
    for i, (article, long) in enumerate(zip(articles, long_flags)):
        content = _clean_content(_strip_title_prefix(article.content_text or "", article.title or ""))
        stories.append({
            "id": i,
            "title": article.title,
            "content": content[:2500],
            "sentence_count": ELABORATE_SENTENCES if long else DIGEST_SENTENCES,
        })

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarize newsletter news stories for a reading app. "
                    "Return only valid JSON: {\"summaries\": [{\"id\": 0, \"summary\": \"...\"}]}. "
                    "Each summary must be clear informative prose (no bullets, no markdown). "
                    "Explain what happened, who is involved, and why it matters."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"stories": stories}, ensure_ascii=False),
            },
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    by_id = {item.get("id"): item.get("summary", "").strip() for item in data.get("summaries", [])}
    return [by_id.get(i, "") for i in range(len(articles))]
