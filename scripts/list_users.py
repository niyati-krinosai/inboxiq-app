"""List InboxIQ users and sync stats — run with production DATABASE_URL set."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.article import Article
from app.models.newsletter import Newsletter
from app.models.user import User


async def main(search: str = "") -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = list(result.scalars().all())
        needle = search.lower()
        for u in users:
            if needle and needle not in (u.email or "").lower() and needle not in (u.name or "").lower():
                continue
            nl = (await db.execute(
                select(func.count()).where(Newsletter.user_id == u.id)
            )).scalar() or 0
            arts = (await db.execute(
                select(func.count()).where(Article.user_id == u.id)
            )).scalar() or 0
            print(
                f"{u.name or '?'} | {u.email} | id={u.id} | "
                f"sync={u.sync_status} complete={u.initial_sync_complete} | "
                f"newsletters={nl} articles={arts} | gmail={u.gmail_connected}"
            )


if __name__ == "__main__":
    term = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    asyncio.run(main(term))
