import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.services.html_cleaner import CleanedContent, clean_newsletter_html


@dataclass
class ArticleSegment:
    title: str
    content: str
    url: str | None = None
    links: list[dict] | None = None


MIN_ARTICLE_LENGTH = 60
MAX_SEGMENTS_PER_ISSUE = 35

_JUNK_TITLE = re.compile(
    r"(unsubscribe|view in browser|apply now|click here|regards|team unstop|"
    r"explore more|what do you think|view more|call for papers|internships?\s+\d)",
    re.IGNORECASE,
)


def segment_newsletter(cleaned: CleanedContent, subject: str | None = None) -> list[ArticleSegment]:
    """Phase 5: split one newsletter issue into many independent articles."""
    if not cleaned.text and not subject:
        return []

    segments: list[ArticleSegment] = []

    # Strategy 1: double-newline blocks with title-like first line
    blocks = re.split(r"\n{2,}", cleaned.text)
    if len(blocks) >= 3:
        for block in blocks:
            block = block.strip()
            if len(block) < MIN_ARTICLE_LENGTH:
                continue
            lines = block.split("\n", 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else block
            if len(title) > 120:
                title = title[:120] + "..."
            if _JUNK_TITLE.search(title):
                continue
            url = _match_link_for_block(title, body, cleaned.links)
            if not url and len(body) < 80:
                continue
            segments.append(ArticleSegment(title=title, content=body, url=url, links=cleaned.links))

    if len(segments) >= 2:
        return _cap_segments(segments)

    # Strategy 2: ALL-CAPS or short first-line titles per paragraph group
    segments = []
    current_title = subject or ""
    current_lines: list[str] = []

    for line in cleaned.text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current_lines and len("\n".join(current_lines)) >= MIN_ARTICLE_LENGTH:
                segments.append(_make_segment(current_title, current_lines, cleaned.links))
                current_lines = []
            continue

        if _looks_like_title(stripped) and current_lines:
            if len("\n".join(current_lines)) >= MIN_ARTICLE_LENGTH:
                segments.append(_make_segment(current_title, current_lines, cleaned.links))
            current_title = stripped
            current_lines = []
        else:
            if not current_title:
                current_title = stripped[:80]
            current_lines.append(stripped)

    if current_lines and len("\n".join(current_lines)) >= MIN_ARTICLE_LENGTH:
        segments.append(_make_segment(current_title, current_lines, cleaned.links))

    if len(segments) >= 2:
        return _cap_segments(segments)

    # Strategy 3: numbered items (common in TLDR-style newsletters)
    numbered = re.split(r"\n(?=\d+[\.\)]\s)", cleaned.text)
    if len(numbered) >= 3:
        for block in numbered:
            block = re.sub(r"^\d+[\.\)]\s*", "", block.strip())
            if len(block) >= MIN_ARTICLE_LENGTH:
                lines = block.split("\n", 1)
                title = lines[0][:120]
                if _JUNK_TITLE.search(title):
                    continue
                body = lines[1] if len(lines) > 1 else block
                segments.append(ArticleSegment(
                    title=title,
                    content=body.strip(),
                    url=_match_link_for_block(title, body, cleaned.links),
                    links=cleaned.links,
                ))

    if len(segments) >= 2:
        return _cap_segments(segments)

    text = cleaned.text or subject or ""
    if text:
        title = subject or text.split("\n")[0][:120]
        return [ArticleSegment(
            title=title,
            content=text,
            url=cleaned.links[0]["url"] if cleaned.links else None,
            links=cleaned.links,
        )]

    return []


def segment_from_html(html: str, subject: str | None = None) -> list[ArticleSegment]:
    """Prefer format-specific parsers (TLDR plain text, HTML headings) before heuristics."""
    if html and _looks_like_tldr_plaintext(html):
        tldr_segments = _segment_tldr_plaintext(html)
        if len(tldr_segments) >= 2:
            return _cap_segments(tldr_segments)

    heading_segments = _segment_by_html_headings(html)
    if len(heading_segments) >= 2:
        return _cap_segments(heading_segments)

    cleaned = clean_newsletter_html(html)
    if cleaned.text and _looks_like_tldr_plaintext(cleaned.text):
        tldr_segments = _segment_tldr_plaintext(cleaned.text)
        if len(tldr_segments) >= 2:
            return _cap_segments(tldr_segments)

    return segment_newsletter(cleaned, subject)


def _looks_like_tldr_plaintext(text: str) -> bool:
    return bool(
        re.search(r"\(\d+\s*MINUTE\s*READ\)\s*\[\d+\]", text, re.IGNORECASE)
        or (re.search(r"TLDR", text) and "Links:" in text and re.search(r"\[\d+\]\s+https?://", text))
    )


def _parse_tldr_link_map(text: str) -> dict[int, str]:
    links: dict[int, str] = {}
    if "Links:" not in text:
        return links
    section = text.split("Links:", 1)[1]
    for match in re.finditer(r"\[(\d+)\]\s+(https?://\S+)", section):
        links[int(match.group(1))] = match.group(2)
    return links


def _segment_tldr_plaintext(text: str) -> list[ArticleSegment]:
    """Parse TLDR's plain-text format: TITLE (N MINUTE READ) [ref] + body + Links footer."""
    link_map = _parse_tldr_link_map(text)
    main = text.split("Links:", 1)[0]

    marker = re.compile(
        r"\(\s*(?:(\d+)\s*)?MINUTE\s*READ\s*\)\s*\[(\d+)\]|\(WEBSITE\)\s*\[(\d+)\]",
        re.IGNORECASE,
    )
    hits = list(marker.finditer(main))
    if len(hits) < 2:
        return []

    segments: list[ArticleSegment] = []
    for i, hit in enumerate(hits):
        ref = int(hit.group(2) or hit.group(3))
        prev_end = hits[i - 1].end() if i > 0 else 0
        body_end = hits[i + 1].start() if i + 1 < len(hits) else len(main)

        gap = main[prev_end:hit.start()]
        paren_pos = gap.rfind("(")
        tail = gap[max(0, paren_pos - 280) : paren_pos].strip()
        lines = [ln.strip() for ln in tail.split("\n") if ln.strip()]
        title_lines: list[str] = []
        for line in reversed(lines):
            alpha = [c for c in line if c.isalpha()]
            upper_ratio = sum(1 for c in alpha if c.isupper()) / max(len(alpha), 1)
            if upper_ratio > 0.45 or (len(line) < 90 and line[0].isupper() and not line.endswith(".")):
                title_lines.insert(0, line)
            else:
                break
            if len(title_lines) >= 2:
                break
        raw_title = " ".join(title_lines) if title_lines else (lines[-1] if lines else "")
        raw_title = re.sub(r"\s+", " ", raw_title)

        body = main[hit.end() : body_end].strip()
        body = re.sub(r"\s+", " ", body)

        if raw_title.isupper() and len(raw_title.split()) <= 6:
            continue
        if _JUNK_TITLE.search(raw_title) or "SPONSOR" in raw_title.upper():
            continue
        if "TOGETHER WITH" in raw_title.upper() or raw_title.upper().startswith("TLDR AI 20"):
            continue
        if len(body) < 30 or len(raw_title) < 8:
            continue

        title = raw_title[:120]
        url = link_map.get(ref)
        segments.append(ArticleSegment(title=title, content=body, url=url))

    return segments


def _segment_by_html_headings(html: str) -> list[ArticleSegment]:
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    headings = soup.find_all(["h1", "h2", "h3", "h4"])
    if len(headings) < 2:
        return []

    links: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "unsubscribe" not in href.lower():
            links.append({"url": href, "text": a.get_text(strip=True) or href})

    segments: list[ArticleSegment] = []
    for i, heading in enumerate(headings):
        title = heading.get_text(" ", strip=True)
        if not title or len(title) < 5 or _JUNK_TITLE.search(title):
            continue

        parts: list[str] = []
        for sib in heading.next_siblings:
            if getattr(sib, "name", None) in ("h1", "h2", "h3", "h4"):
                break
            if hasattr(sib, "get_text"):
                text = sib.get_text(" ", strip=True)
            else:
                text = str(sib).strip()
            if text:
                parts.append(text)

        body = " ".join(parts).strip()
        if len(body) < 30:
            continue

        segments.append(ArticleSegment(
            title=title[:120],
            content=body,
            url=_match_link_for_block(title, body, links),
            links=links,
        ))

    return segments


def _cap_segments(segments: list[ArticleSegment]) -> list[ArticleSegment]:
    filtered = [s for s in segments if not _JUNK_TITLE.search(s.title)]
    if not filtered:
        filtered = segments
    return filtered[:MAX_SEGMENTS_PER_ISSUE]


def _looks_like_title(line: str) -> bool:
    if len(line) < 5 or len(line) > 150:
        return False
    if line.isupper() and len(line) < 100:
        return True
    if line.endswith(":") and len(line) < 100:
        return True
    if re.match(r"^[A-Z][^.!?]*$", line) and len(line.split()) <= 12:
        return True
    return False


def _make_segment(title: str, lines: list[str], links: list[dict]) -> ArticleSegment:
    body = "\n".join(lines)
    return ArticleSegment(
        title=title[:120],
        content=body,
        url=_match_link_for_block(title, body, links),
        links=links,
    )


def _match_link_for_block(title: str, body: str, links: list[dict]) -> str | None:
    combined = (title + " " + body).lower()
    for link in links:
        link_text = (link.get("text") or "").lower()
        if link_text and len(link_text) > 8 and link_text in combined:
            return link["url"]
    for link in links:
        url = link.get("url", "")
        if url and "utm_" not in url and "mailchi.mp" not in url:
            return url
    return links[0]["url"] if links else None
