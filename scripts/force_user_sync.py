"""Force Gmail import + article processing for a user on production.

Usage (set External Database URL from Render Postgres Connect tab):
  set DATABASE_URL=postgresql://...
  python scripts/force_user_sync.py --search gupta
  python scripts/force_user_sync.py --email mentor@gmail.com
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.article import Article
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.gmail_sync import initial_sync, incremental_sync
from app.services.pipeline import run_light_pipeline_batch


async def _stats(db, user_id) -> tuple[int, int]:
    nl = (await db.execute(select(func.count()).where(Newsletter.user_id == user_id))).scalar() or 0
    arts = (await db.execute(select(func.count()).where(Article.user_id == user_id))).scalar() or 0
    return nl, arts


async def main(search: str | None, email: str | None, reset: bool) -> None:
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: Set DATABASE_URL to Render External Database URL first.")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        stmt = select(User).order_by(User.created_at.desc())
        if email:
            stmt = stmt.where(User.email == email)
        elif search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(User.email.ilike(like), User.name.ilike(like))
            )
        users = list((await db.execute(stmt)).scalars().all())

        if not users:
            print("No users matched.")
            sys.exit(1)

        print(f"Matched {len(users)} user(s):\n")
        for u in users:
            nl, arts = await _stats(db, u.id)
            print(
                f"  {u.name or '?'} | {u.email} | id={u.id}\n"
                f"    gmail={u.gmail_connected} sync={u.sync_status} "
                f"complete={u.initial_sync_complete} | nl={nl} articles={arts}"
            )

        user = users[0]
        if len(users) > 1:
            print(f"\nSyncing first match: {user.email}")

        if reset:
            user.initial_sync_complete = False
            user.sync_status = "idle"
            await db.commit()
            print("Reset sync flags.")

        if not user.gmail_connected:
            print("ERROR: User has no Gmail connected — they must sign in via Google first.")
            sys.exit(1)

        print("\nStarting Gmail sync...")
        if not user.initial_sync_complete:
            result = await initial_sync(db, user)
        else:
            result = await incremental_sync(db, user)
        await db.commit()
        print("Gmail sync result:", result)

        print("Processing articles...")
        pipe = await run_light_pipeline_batch(db, user.id, limit=100)
        await db.commit()
        print("Pipeline result:", pipe)

        nl, arts = await _stats(db, user.id)
        print(f"\nDone. newsletters={nl} articles={arts}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--search", help="Match name or email substring")
    p.add_argument("--email", help="Exact email")
    p.add_argument("--reset", action="store_true", help="Reset sync flags before import")
    args = p.parse_args()
    if not args.search and not args.email:
        p.error("Provide --search or --email")
    asyncio.run(main(args.search, args.email, args.reset))
