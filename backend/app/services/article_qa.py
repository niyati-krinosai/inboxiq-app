"""Answer follow-up questions about a specific article using full context."""

import re

from app.config import get_settings
from app.core.logging import get_logger
from app.models.article import Article
from app.providers.openai_client import create_openai_client
from app.services.article_summary import _clean_content, _strip_title_prefix

settings = get_settings()
log = get_logger(__name__)
client = create_openai_client()

QA_SYSTEM = (
    "You are InboxIQ, a personal newsletter assistant. The user is asking about a "
    "specific story from their inbox. Answer using ONLY the article context provided. "
    "Be specific, accurate, and conversational. If the context does not contain the "
    "answer, say what is known and what is not covered in their newsletter. "
    "No markdown bullets unless listing 3+ distinct items."
)


def build_article_context(article: Article, newsletter_name: str) -> str:
    content = _clean_content(
        _strip_title_prefix(article.content_text or "", article.title or "")
    )
    parts = [
        f"Title: {article.title}",
        f"Newsletter: {newsletter_name}",
        f"Categories: {', '.join(article.categories or [])}",
    ]
    if article.companies:
        parts.append(f"Companies: {', '.join(article.companies)}")
    if article.products:
        parts.append(f"Products: {', '.join(article.products)}")
    if article.short_summary:
        parts.append(f"Summary: {article.short_summary}")
    if article.why_it_matters:
        parts.append(f"Why it matters: {article.why_it_matters}")
    if article.business_impact:
        parts.append(f"Business impact: {article.business_impact}")
    if article.technical_impact:
        parts.append(f"Technical impact: {article.technical_impact}")
    if article.developer_takeaway:
        parts.append(f"Developer takeaway: {article.developer_takeaway}")
    if content:
        parts.append(f"Full article text:\n{content[:8000]}")
    if article.enriched_content:
        parts.append(f"Official source excerpt:\n{article.enriched_content[:3000]}")
    link = article.url or article.official_link or article.newsletter_link
    if link:
        parts.append(f"Source URL: {link}")
    return "\n\n".join(parts)


async def answer_article_question(
    article: Article,
    newsletter_name: str,
    question: str,
    conversation: list[dict] | None = None,
) -> str:
    context = build_article_context(article, newsletter_name)
    if not client or not settings.openai_api_key:
        return _fallback_answer(article, newsletter_name, question, context)

    messages: list[dict] = [{"role": "system", "content": QA_SYSTEM}]
    messages.append({
        "role": "user",
        "content": f"Article context:\n{context}\n\n---\nI will ask questions about this story.",
    })
    messages.append({
        "role": "assistant",
        "content": "Understood. Ask me anything about this story from your newsletter.",
    })

    for turn in (conversation or [])[-8:]:
        role = turn.get("role")
        content = turn.get("content") or turn.get("headline") or ""
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)[:2000]})

    messages.append({"role": "user", "content": question})

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.35,
            max_tokens=1200,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or _fallback_answer(article, newsletter_name, question, context)
    except Exception as exc:
        log.warning("article_qa_llm_failed", error=str(exc))
        return _fallback_answer(article, newsletter_name, question, context)


def _fallback_answer(
    article: Article,
    newsletter_name: str,
    question: str,
    context: str,
) -> str:
    q = question.lower()
    snippets = re.split(r"(?<=[.!?])\s+", context)
    hits = [s for s in snippets if any(w in s.lower() for w in q.split() if len(w) > 4)]
    if hits:
        return (
            f"From \"{article.title}\" ({newsletter_name}):\n\n"
            + " ".join(hits[:4])
        )
    return (
        f"I found \"{article.title}\" in {newsletter_name}, but I need an API key "
        "configured for detailed follow-up answers. Try asking with more specific keywords "
        "from the story."
    )
