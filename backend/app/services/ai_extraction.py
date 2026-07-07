import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import CATEGORIES
from app.core.logging import get_logger
from app.models.article import Article
from app.providers.registry import get_embedding_provider, get_extraction_provider
from app.services.source_enrichment import enrich_article_sources

settings = get_settings()
log = get_logger(__name__)

EXTRACTION_SYSTEM = "Extract structured knowledge from newsletter articles. Return only valid JSON."

EXTRACTION_PROMPT = """Required JSON schema:
{
  "title": "string",
  "summary": "string (2-3 sentences)",
  "category": "primary category",
  "categories": ["multiple categories from: """ + ", ".join(CATEGORIES) + """"],
  "subcategory": "string or null",
  "companies": [], "people": [], "products": [], "frameworks": [], "models": [],
  "apis": [], "repositories": [], "funding": [], "technologies": [], "topics": [],
  "date": "ISO date or null",
  "official_link": "url or null",
  "newsletter_link": "url or null",
  "importance_score": 0.0-1.0,
  "novelty_score": 0.0-1.0,
  "short_summary": "one sentence",
  "why_it_matters": "1-2 sentences",
  "developer_takeaway": "1 sentence",
  "business_impact": "1-2 sentences or null",
  "technical_impact": "1-2 sentences or null"
}

Article content:
"""


def _fallback_extraction(content: str) -> dict:
    words = content.split()
    title = " ".join(words[:12]) + ("..." if len(words) > 12 else "")
    return {
        "title": title, "summary": content[:300], "category": "AI", "categories": ["AI"],
        "companies": [], "people": [], "products": [], "frameworks": [], "models": [],
        "apis": [], "repositories": [], "funding": [], "technologies": [], "topics": [],
        "importance_score": 0.5, "novelty_score": 0.5,
        "short_summary": content[:150], "why_it_matters": content[:200],
        "developer_takeaway": "Review the full article.", "business_impact": None,
        "technical_impact": "See article for details.",
    }


async def generate_embedding(text: str, tracer=None) -> list[float] | None:
    try:
        provider = get_embedding_provider()
        embedding, usage = await provider.embed(text)
        if tracer:
            tracer.record_usage(usage)
        return embedding
    except Exception as exc:
        log.warning("generate_embedding_failed", error=str(exc))
        return None


async def extract_and_embed_article(
    db: AsyncSession,
    article: Article,
    tracer=None,
) -> Article:
    enriched_content, enriched_sources = await enrich_article_sources(
        article.url, None, article.content_text or "",
    )

    provider = get_extraction_provider()
    content = (article.content_text or "")[:6000]
    if enriched_content:
        content += f"\n\n--- OFFICIAL SOURCE ---\n{enriched_content[:4000]}"

    try:
        result = await provider.extract(
            EXTRACTION_PROMPT + content,
            EXTRACTION_SYSTEM,
            settings.extraction_prompt_version,
        )
        metadata = result.data
        if tracer:
            tracer.record_usage(result.usage)
    except Exception:
        metadata = _fallback_extraction(article.content_text or "")

    _apply_metadata(article, metadata, enriched_content, enriched_sources)

    embedding_text = f"{article.title}\n{article.short_summary or ''}\n{article.content_text or ''}"[:8000]
    article.embedding = await generate_embedding(embedding_text, tracer=tracer)

    # Model versioning metadata
    versions = settings.model_versions()
    article.metadata_json = {
        **metadata,
        "_model_versions": versions,
    }
    article.processing_status = "extracted"
    article.processed_at = datetime.now(timezone.utc)
    await db.flush()
    return article


def _apply_metadata(article: Article, metadata: dict, enriched_content, enriched_sources) -> None:
    article.title = metadata.get("title", article.title)
    article.categories = metadata.get("categories", [])
    article.subcategory = metadata.get("subcategory")
    article.companies = metadata.get("companies", [])
    article.products = metadata.get("products", [])
    article.frameworks = metadata.get("frameworks", [])
    article.apis = metadata.get("apis", [])
    article.models = metadata.get("models", [])
    article.repositories = metadata.get("repositories", [])
    article.people = metadata.get("people", [])
    article.technologies = metadata.get("technologies", [])
    article.topics = metadata.get("topics", [])
    article.funding = metadata.get("funding", [])
    article.importance_score = metadata.get("importance_score", 0.5)
    article.novelty_score = metadata.get("novelty_score", 0.5)
    article.short_summary = metadata.get("short_summary") or metadata.get("summary")
    article.why_it_matters = metadata.get("why_it_matters")
    article.developer_takeaway = metadata.get("developer_takeaway")
    article.business_impact = metadata.get("business_impact")
    article.technical_impact = metadata.get("technical_impact")
    article.impact = metadata.get("technical_impact")
    article.official_link = metadata.get("official_link") or article.url
    article.newsletter_link = metadata.get("newsletter_link") or article.url
    article.url = article.official_link
    article.enriched_content = enriched_content
    article.enriched_sources = enriched_sources
