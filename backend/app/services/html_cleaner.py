import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, NavigableString


@dataclass
class CleanedContent:
    text: str
    links: list[dict]  # {url, text}
    code_blocks: list[str]


COPYRIGHT_PATTERN = re.compile(
    r"(©|copyright|all rights reserved|confidentiality notice)",
    re.IGNORECASE,
)

REMOVE_SELECTORS = [
    "nav", "header", "footer", "aside", "menu",
    "[class*='unsubscribe']", "[class*='footer']", "[class*='foot']",
    "[class*='social']", "[class*='share']", "[class*='follow']",
    "[class*='promo']", "[class*='ad-']", "[class*='advert']",
    "[class*='sponsor']", "[class*='banner']",
    "[id*='unsubscribe']", "[id*='footer']",
    "[class*='copyright']",
]

REMOVE_TEXT = re.compile(
    r"(unsubscribe|view in browser|manage preferences|"
    r"update your preferences|email preferences|"
    r"you received this email because|click here to unsubscribe|"
    r"no longer wish to receive|opt out|privacy policy)",
    re.IGNORECASE,
)


def clean_newsletter_html(html: str) -> CleanedContent:
    """Phase 4: strip noise, keep headlines, body, links, code, announcements."""
    if not html or not html.strip():
        return CleanedContent(text="", links=[], code_blocks=[])

    soup = BeautifulSoup(html, "lxml")

    # Remove comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove scripts, styles, tracking, images
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "svg", "img", "picture", "video"]):
        tag.decompose()

    for selector in REMOVE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    # Remove tracking pixels (1x1 images already gone; catch inline)
    for el in soup.find_all(attrs={"width": "1"}):
        el.decompose()
    for el in soup.find_all(attrs={"height": "1"}):
        el.decompose()

    # Remove copyright / unsubscribe text blocks
    for el in soup.find_all(string=REMOVE_TEXT):
        parent = el.parent
        if parent and parent.name in ("p", "div", "span", "td", "li", "font"):
            parent.decompose()

    for el in soup.find_all(string=COPYRIGHT_PATTERN):
        parent = el.parent
        if parent:
            parent.decompose()

    # Extract links before flattening
    links: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if href.startswith("http") and "unsubscribe" not in href.lower():
            links.append({"url": href, "text": text or href})

    # Extract code blocks
    code_blocks: list[str] = []
    for code in soup.find_all(["code", "pre"]):
        text = code.get_text(strip=True)
        if len(text) > 10:
            code_blocks.append(text)

    # Preserve headings with markdown-style markers
    for level in range(1, 5):
        for h in soup.find_all(f"h{level}"):
            h.insert_before(NavigableString("\n"))
            h.insert_after(NavigableString("\n"))

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return CleanedContent(text=text, links=links, code_blocks=code_blocks)
