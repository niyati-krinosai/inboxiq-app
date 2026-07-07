import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

GITHUB_RELEASE_PATTERN = re.compile(r"github\.com/[\w.-]+/[\w.-]+/releases")
DOCS_PATTERNS = ("docs.", "/docs/", "documentation", "readthedocs.io", "gitbook.io")


async def fetch_url_text(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=settings.enrich_fetch_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "InboxIQ/1.0 (source-enrichment)"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                return None
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return re.sub(r"\n{3,}", "\n\n", text)[:12000]
    except Exception as e:
        log.warning("enrich_fetch_failed", url=url, error=str(e))
        return None


def classify_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "github.com" in host:
        if "/releases" in url:
            return "github_release"
        return "github"
    if any(p in url.lower() for p in DOCS_PATTERNS):
        return "documentation"
    if any(p in host for p in ("openai.com", "anthropic.com", "google.com", "meta.com", "microsoft.com")):
        return "official_blog"
    return "web"


async def enrich_article_sources(
    official_url: str | None,
    supporting_urls: list[str] | None,
    newsletter_content: str,
) -> tuple[str | None, list[dict]]:
    """
    Architectural improvement: merge newsletter extraction with official source content.
    Newsletters are the discovery mechanism; official sources provide depth.
    """
    if not settings.enrich_official_sources:
        return None, []

    urls: list[str] = []
    if official_url:
        urls.append(official_url)
    for u in (supporting_urls or []):
        if u not in urls:
            urls.append(u)

    # Extract URLs embedded in newsletter content
    for match in re.finditer(r"https?://[^\s<>\"']+", newsletter_content):
        u = match.group(0).rstrip(".,)")
        if "unsubscribe" not in u.lower() and u not in urls:
            urls.append(u)

    urls = urls[: settings.enrich_max_urls_per_article]

    enriched_parts: list[str] = []
    source_records: list[dict] = []

    for url in urls:
        text = await fetch_url_text(url)
        if not text:
            continue
        source_type = classify_url(url)
        enriched_parts.append(f"[{source_type.upper()}] {url}\n{text[:4000]}")
        source_records.append({"url": url, "type": source_type, "chars": len(text)})

    if not enriched_parts:
        return None, source_records

    merged = "\n\n---\n\n".join(enriched_parts)
    return merged[:15000], source_records
