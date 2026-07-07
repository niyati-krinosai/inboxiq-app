"""Article summary generation tests."""

from app.models.article import Article
from app.services.article_summary import heuristic_article_summary, _looks_like_raw_snippet


def test_heuristic_skips_junk_and_title_repeat():
    article = Article(
        title="OPENAI LAUNCHES GPT-5",
        content_text=(
            "OPENAI LAUNCHES GPT-5\n"
            "OpenAI announced GPT-5 today with stronger reasoning and coding skills. "
            "The model will roll out to ChatGPT Plus users over the next week. "
            "Developers can access it through the API with updated pricing. "
            "View in browser: https://example.com\n"
            "Unsubscribe here"
        ),
    )
    summary = heuristic_article_summary(article)
    assert "unsubscribe" not in summary.lower()
    assert "view in browser" not in summary.lower()
    assert "gpt-5" in summary.lower()
    assert len(summary) > 80


def test_raw_snippet_detection():
    title = "TESLA CAPS EMPLOYEE AI SPENDING AT $200 PER WEEK EXCEPT FOR GROK"
    raw = title + " Tesla"
    assert _looks_like_raw_snippet(raw, title) is True


def test_elaborate_summary_is_longer():
    article = Article(
        title="Anthropic releases Claude 4",
        content_text=" ".join(
            f"Sentence {i} explains a distinct part of the Claude 4 release announcement."
            for i in range(1, 12)
        ),
    )
    short = heuristic_article_summary(article, long=False)
    long = heuristic_article_summary(article, long=True)
    assert len(long) >= len(short)
