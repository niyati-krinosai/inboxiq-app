"""Fetch ALL TLDR newsletter variants for a user (not just TLDR AI).

Usage:
  set DATABASE_URL=...
  set TOKEN_ENCRYPTION_KEY=...
  set GOOGLE_CLIENT_ID=...
  set GOOGLE_CLIENT_SECRET=...
  python scripts/fetch_tldr_for_user.py --email krsgupta@ucdavis.edu
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.article import Article
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.gmail_sync import _collect_message_ids, discover_and_import_messages
from app.services.google_oauth import get_gmail_service
from app.services.pipeline import run_light_pipeline_batch

# Broad TLDR discovery — all product lines, all mailboxes, long history
TLDR_QUERIES = [
    "in:anywhere from:tldrnewsletter.com",
    "in:anywhere from:tldr.tech",
    "from:tldrnewsletter.com",
    "from:tldr.tech",
    "list:tldrnewsletter.com OR list:tldr.tech",
    "newer_than:5y from:tldrnewsletter.com",
    "newer_than:5y from:tldr.tech",
    "from:(dan@tldrnewsletter.com OR hello@tldrnewsletter.com OR team@tldrnewsletter.com OR news@tldrnewsletter.com OR ai@tldrnewsletter.com)",
    "from:tldr subject:TLDR",
]


async def _stats(db, user_id) -> dict:
    nls = list(
        (
            await db.execute(
                select(Newsletter).where(Newsletter.user_id == user_id).where(
                    or_(
                        Newsletter.name.ilike("%tldr%"),
                        Newsletter.sender_email.ilike("%tldr%"),
                        Newsletter.domain.ilike("%tldr%"),
                    )
                )
            )
        ).scalars().all()
    )
    out = []
    total_issues = 0
    for n in nls:
        issues = (
            await db.execute(select(func.count()).select_from(Issue).where(Issue.newsletter_id == n.id))
        ).scalar() or 0
        total_issues += issues
        out.append({"name": n.name, "email": n.sender_email, "issues": issues})
    arts = (
        await db.execute(select(func.count()).where(Article.user_id == user_id))
    ).scalar() or 0
    return {"tldr_newsletters": out, "tldr_count": len(out), "tldr_issues": total_issues, "all_articles": arts}


async def main(email: str, max_messages: int) -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            print(f"No user: {email}")
            sys.exit(1)
        if not user.gmail_connected and not (user.access_token and user.refresh_token):
            print("Gmail not connected")
            sys.exit(1)
        user.gmail_connected = True
        user.sync_status = "syncing"
        await db.commit()

        before = await _stats(db, user.id)
        print("BEFORE:", before, flush=True)

        service = get_gmail_service(user)
        print(f"Collecting TLDR message IDs (cap={max_messages})...", flush=True)
        message_ids = await _collect_message_ids(service, TLDR_QUERIES, max_messages)
        print(f"Found {len(message_ids)} unique TLDR-related Gmail messages", flush=True)

        # Re-load user after possible token refresh
        user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        result = await discover_and_import_messages(db, user, message_ids)
        await db.commit()
        print("Import result:", result, flush=True)

        # Process into articles
        for i in range(50):
            pipe = await run_light_pipeline_batch(db, user.id, limit=200)
            await db.commit()
            print(f"Pipeline batch {i+1}:", pipe, flush=True)
            if pipe.get("processed", 0) == 0:
                break

        user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        user.sync_status = "idle"
        await db.commit()

        after = await _stats(db, user.id)
        print("AFTER:", after, flush=True)
        print("DONE", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--max", type=int, default=5000)
    args = p.parse_args()
    asyncio.run(main(args.email, args.max))
