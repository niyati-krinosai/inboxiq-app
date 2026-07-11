"""Check Krishna TLDR article counts in DB vs API."""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.article import Article
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.auth import create_access_token


async def main() -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == "krsgupta@ucdavis.edu"))).scalar_one()
        nl_ids = list(
            (
                await db.execute(
                    select(Newsletter.id).where(
                        Newsletter.user_id == u.id,
                        or_(
                            Newsletter.name.ilike("%tldr%"),
                            Newsletter.sender_email.ilike("%tldr%"),
                        ),
                    )
                )
            ).scalars().all()
        )
        arts = (
            await db.execute(
                select(func.count()).select_from(Article).join(Issue).where(Issue.newsletter_id.in_(nl_ids))
            )
        ).scalar() or 0
        pending = (
            await db.execute(
                select(func.count()).where(
                    Issue.newsletter_id.in_(nl_ids),
                    Issue.processing_status.in_(["imported", "segmented", "failed", "cleaned"]),
                )
            )
        ).scalar() or 0
        by_status = (
            await db.execute(
                select(Issue.processing_status, func.count())
                .where(Issue.newsletter_id.in_(nl_ids))
                .group_by(Issue.processing_status)
            )
        ).all()
        print("tldr_articles", arts)
        print("pending_issues", pending)
        print("issue_statuses", dict(by_status))
        print("user", u.sync_status, u.initial_sync_complete, u.gmail_connected)

        for n in (
            await db.execute(select(Newsletter).where(Newsletter.id.in_(nl_ids)).order_by(Newsletter.name))
        ).scalars():
            real = (
                await db.execute(
                    select(func.count()).select_from(Article).join(Issue).where(Issue.newsletter_id == n.id)
                )
            ).scalar() or 0
            print(f"  {n.name}: stored={n.article_count} real={real} issues={n.issue_count}")

        token = create_access_token(u.id, u.email)

    async with httpx.AsyncClient(timeout=60) as c:
        h = {"Authorization": f"Bearer {token}"}
        r = await c.get("https://inboxiq-api.onrender.com/api/v1/sync/status", headers=h)
        print("API sync", r.json())
        r2 = await c.get("https://inboxiq-api.onrender.com/api/v1/newsletters", headers=h)
        tldr = [n for n in r2.json() if "tldr" in (n.get("name") or "").lower()]
        print("API tldr newsletters", len(tldr))
        for n in tldr:
            print(f"  {n.get('name')}: issues={n.get('issue_count')} articles={n.get('article_count')}")
            # fetch articles endpoint
            ra = await c.get(
                f"https://inboxiq-api.onrender.com/api/v1/newsletters/{n['id']}/articles?limit=5000",
                headers=h,
            )
            data = ra.json()
            count = len(data) if isinstance(data, list) else len(data.get("articles", data.get("items", [])))
            print(f"    articles_endpoint_returned={count} status={ra.status_code}")


if __name__ == "__main__":
    asyncio.run(main())
