"""Phase 20: Newsletter analytics dashboard data."""

import uuid
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article, CanonicalEvent, EventSource
from app.models.newsletter import Newsletter


async def get_analytics(db: AsyncSession, user_id: uuid.UUID) -> dict:
    newsletters = (await db.execute(
        select(Newsletter).where(Newsletter.user_id == user_id)
    )).scalars().all()

    category_counter: Counter = Counter()
    company_counter: Counter = Counter()
    topic_counter: Counter = Counter()
    nl_categories: dict[str, Counter] = defaultdict(Counter)

    articles = (await db.execute(
        select(Article).where(Article.user_id == user_id)
    )).scalars().all()

    nl_map = {n.id: n.name for n in newsletters}

    for a in articles:
        for cat in (a.categories or []):
            category_counter[cat] += 1
            nl_categories[nl_map.get(a.newsletter_id, "Unknown")][cat] += 1
        for co in (a.companies or []):
            company_counter[co] += 1
        for t in (a.topics or []):
            topic_counter[t] += 1

    # Newsletter reliability = articles that became canonical events with 2+ sources
    nl_reliability: dict[str, float] = {}
    for nl in newsletters:
        nl_reliability[nl.name] = min((nl.article_count or 0) / max(nl.issue_count, 1), 1.0)

    # Coverage bias per newsletter
    coverage_bias = {}
    for nl_name, cats in nl_categories.items():
        total = sum(cats.values())
        if total:
            top_cat = cats.most_common(1)[0]
            coverage_bias[nl_name] = {
                "primary_focus": top_cat[0],
                "focus_percentage": round(top_cat[1] / total * 100, 1),
                "distribution": dict(cats.most_common(5)),
            }

    # Trending topics from recent events
    events = (await db.execute(
        select(CanonicalEvent)
        .where(CanonicalEvent.user_id == user_id, CanonicalEvent.is_trending == True)  # noqa: E712
        .order_by(CanonicalEvent.ranking_score.desc().nullslast())
        .limit(10)
    )).scalars().all()

    trending = [
        {
            "headline": e.headline,
            "canonical_title": e.canonical_title,
            "newsletter_count": e.newsletter_count,
            "is_breaking": e.is_breaking,
            "ranking_score": e.ranking_score,
        }
        for e in events
    ]

    # Fastest newsletter (most issues per week)
    fastest = sorted(
        newsletters,
        key=lambda n: (n.issue_count or 0) / max((n.last_seen_at - n.first_seen_at).days, 1),
        reverse=True,
    )[:5]

    return {
        "top_sources": [
            {"name": n.name, "issues": n.issue_count, "articles": n.article_count, "frequency": n.frequency}
            for n in sorted(newsletters, key=lambda x: x.issue_count, reverse=True)[:10]
        ],
        "most_reliable": sorted(
            [{"name": k, "score": round(v, 2)} for k, v in nl_reliability.items()],
            key=lambda x: x["score"],
            reverse=True,
        )[:10],
        "most_mentioned_companies": [{"name": k, "count": v} for k, v in company_counter.most_common(15)],
        "trending_topics": [{"topic": k, "count": v} for k, v in topic_counter.most_common(15)],
        "trending_events": trending,
        "fastest_newsletters": [
            {"name": n.name, "issues": n.issue_count, "frequency": n.frequency}
            for n in fastest
        ],
        "coverage_bias": coverage_bias,
        "category_distribution": dict(category_counter.most_common(20)),
    }
