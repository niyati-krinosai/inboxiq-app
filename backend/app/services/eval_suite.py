"""Quality evaluation suite — detect pipeline regressions."""

import json
from pathlib import Path

from app.services.article_segmentation import segment_from_html
from app.services.html_cleaner import clean_newsletter_html

EVALS_DIR = Path(__file__).parent.parent.parent / "evals"
FIXTURES_PATH = EVALS_DIR / "fixtures.json"


def load_fixtures() -> list[dict]:
    if not FIXTURES_PATH.exists():
        return _default_fixtures()
    return json.loads(FIXTURES_PATH.read_text())


def _default_fixtures() -> list[dict]:
    """Built-in benchmark dataset (expand with real newsletter HTML)."""
    return [
        {
            "id": "tldr-multi-article",
            "html": """
            <h2>OpenAI launches GPT-5</h2><p>OpenAI announced GPT-5 today with improved reasoning.</p>
            <hr><h2>Anthropic releases Claude 4</h2><p>Anthropic unveiled Claude 4 with 1M context.</p>
            <hr><h2>New MCP servers</h2><p>Three new MCP servers launched this week.</p>
            """,
            "subject": "TLDR AI",
            "expected_articles_min": 2,
            "expected_entities": ["OpenAI", "Anthropic"],
            "expected_categories": ["AI"],
        },
        {
            "id": "single-announcement",
            "html": "<h1>vLLM 0.5 Released</h1><p>vLLM 0.5 adds speculative decoding support.</p>",
            "subject": "Release Notes",
            "expected_articles_min": 1,
            "expected_entities": ["vLLM"],
            "expected_categories": ["Inference"],
        },
    ]


def run_eval_suite() -> dict:
    """Run pipeline stages on fixtures and compare to expectations."""
    fixtures = load_fixtures()
    results = []

    for fixture in fixtures:
        html = fixture["html"]
        subject = fixture.get("subject")

        cleaned = clean_newsletter_html(html)
        segments = segment_from_html(html, subject)

        article_count = len(segments)
        text_combined = " ".join(s.content for s in segments)
        entities_found = [
            e for e in fixture.get("expected_entities", [])
            if e.lower() in text_combined.lower()
        ]

        passed_articles = article_count >= fixture.get("expected_articles_min", 1)
        passed_entities = len(entities_found) >= len(fixture.get("expected_entities", [])) * 0.5

        results.append({
            "id": fixture["id"],
            "passed": passed_articles and passed_entities,
            "article_count": article_count,
            "expected_articles_min": fixture.get("expected_articles_min"),
            "entities_found": entities_found,
            "expected_entities": fixture.get("expected_entities", []),
            "cleaned_text_length": len(cleaned.text),
        })

    passed = sum(1 for r in results if r["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 2) if results else 0,
        "results": results,
    }
