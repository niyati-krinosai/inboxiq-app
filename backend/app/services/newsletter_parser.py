import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment


@dataclass
class ParsedArticle:
    title: str
    content: str
    url: str | None = None


# Patterns for elements to remove
REMOVE_SELECTORS = [
    "nav", "header", "footer", "aside",
    "[class*='unsubscribe']", "[class*='footer']",
    "[class*='social']", "[class*='share']",
    "[class*='promo']", "[class*='ad']", "[class*='advertisement']",
    "[class*='sponsor']", "[id*='unsubscribe']",
    "img[width='1']", "img[height='1']",
]

REMOVE_TEXT_PATTERNS = re.compile(
    r"(unsubscribe|view in browser|manage preferences|"
    r"update your preferences|email preferences|"
    r"you received this email because)",
    re.IGNORECASE,
)


def _clean_soup(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    for selector in REMOVE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    for img in soup.find_all("img"):
        width = img.get("width", "")
        height = img.get("height", "")
        if str(width) == "1" or str(height) == "1":
            img.decompose()

    for el in soup.find_all(string=REMOVE_TEXT_PATTERNS):
        parent = el.parent
        if parent and parent.name in ("p", "div", "span", "td", "li"):
            parent.decompose()


def _extract_link(el) -> str | None:
    link = el.find("a", href=True)
    if link:
        href = link["href"]
        if href.startswith("http") and "unsubscribe" not in href.lower():
            return href
    return None


def _split_into_articles(soup: BeautifulSoup) -> list[ParsedArticle]:
    """Split newsletter HTML into individual article blocks."""
    articles: list[ParsedArticle] = []

    # Strategy 1: article/section tags
    blocks = soup.find_all(["article", "section"])
    if len(blocks) >= 2:
        for block in blocks:
            title_el = block.find(["h1", "h2", "h3", "h4"])
            title = title_el.get_text(strip=True) if title_el else ""
            text = block.get_text(separator="\n", strip=True)
            if len(text) > 80:
                articles.append(ParsedArticle(
                    title=title or text[:80],
                    content=text,
                    url=_extract_link(block),
                ))
        if articles:
            return articles

    # Strategy 2: heading-delimited sections
    headings = soup.find_all(["h1", "h2", "h3"])
    if len(headings) >= 2:
        for heading in headings:
            title = heading.get_text(strip=True)
            if len(title) < 5:
                continue
            parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h1", "h2", "h3"):
                    break
                text = sibling.get_text(separator="\n", strip=True)
                if text:
                    parts.append(text)
            content = "\n".join(parts)
            if len(content) > 80:
                articles.append(ParsedArticle(
                    title=title,
                    content=content,
                    url=_extract_link(heading.parent) if heading.parent else None,
                ))
        if articles:
            return articles

    # Strategy 3: horizontal rules or hr tags
    hrs = soup.find_all("hr")
    if len(hrs) >= 2:
        sections = re.split(r"<hr[^>]*>", str(soup), flags=re.IGNORECASE)
        for section_html in sections:
            section_soup = BeautifulSoup(section_html, "lxml")
            text = section_soup.get_text(separator="\n", strip=True)
            if len(text) > 100:
                title_el = section_soup.find(["h1", "h2", "h3", "h4", "strong", "b"])
                title = title_el.get_text(strip=True) if title_el else text[:80]
                articles.append(ParsedArticle(title=title, content=text))
        if articles:
            return articles

    # Fallback: treat entire newsletter as one article
    text = soup.get_text(separator="\n", strip=True)
    title_el = soup.find(["h1", "h2"])
    title = title_el.get_text(strip=True) if title_el else (text[:80] if text else "Newsletter Issue")
    if text:
        articles.append(ParsedArticle(title=title, content=text))

    return articles


def parse_newsletter_html(html: str, subject: str | None = None) -> list[ParsedArticle]:
    """Parse newsletter HTML into clean article blocks."""
    if not html or not html.strip():
        if subject:
            return [ParsedArticle(title=subject, content=subject)]
        return []

    soup = BeautifulSoup(html, "lxml")
    _clean_soup(soup)

    articles = _split_into_articles(soup)

    if not articles and subject:
        text = soup.get_text(separator="\n", strip=True)
        articles = [ParsedArticle(title=subject, content=text or subject)]

    return articles
