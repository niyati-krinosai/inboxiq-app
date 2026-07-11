"""Fix Article.newsletter_id after TLDR product split + refresh article_count."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, or_, select, text, update

from app.database import AsyncSessionLocal
from app.models.article import Article
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.user import User


async def main(email: str) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        tldr_ids = list(
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

        # Realign article.newsletter_id to the issue's current newsletter
        result = await db.execute(
            text(
                """
                UPDATE articles AS a
                SET newsletter_id = i.newsletter_id
                FROM issues AS i
                WHERE a.issue_id = i.id
                  AND i.newsletter_id = ANY(:nl_ids)
                  AND a.newsletter_id IS DISTINCT FROM i.newsletter_id
                """
            ),
            {"nl_ids": tldr_ids},
        )
        print(f"Updated article newsletter_id rows: {result.rowcount}", flush=True)

        # Refresh article_count / issue_count on each TLDR newsletter
        for nid in tldr_ids:
            arts = (
                await db.execute(
                    select(func.count()).where(Article.newsletter_id == nid, Article.user_id == u.id)
                )
            ).scalar() or 0
            issues = (
                await db.execute(select(func.count()).where(Issue.newsletter_id == nid))
            ).scalar() or 0
            await db.execute(
                update(Newsletter)
                .where(Newsletter.id == nid)
                .values(article_count=arts, issue_count=issues)
            )
            n = (await db.execute(select(Newsletter).where(Newsletter.id == nid))).scalar_one()
            print(f"  {n.name}: issues={issues} articles={arts}", flush=True)

        await db.commit()
        total = (
            await db.execute(
                select(func.count()).where(
                    Article.user_id == u.id, Article.newsletter_id.in_(tldr_ids)
                )
            )
        ).scalar() or 0
        print(f"TOTAL TLDR articles visible by newsletter_id: {total}", flush=True)


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "krsgupta@ucdavis.edu"
    asyncio.run(main(email))
