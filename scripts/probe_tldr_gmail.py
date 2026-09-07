"""Probe how many TLDR messages exist in a user's Gmail vs DB."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.gmail_sync import _collect_message_ids, _gmail_execute
from app.services.google_oauth import get_gmail_service

QUERIES = [
    "from:tldrnewsletter.com",
    "from:tldr.tech",
    "from:tldr",
    "list:tldrnewsletter.com",
    "in:anywhere from:tldrnewsletter.com",
    "in:anywhere from:tldr.tech",
    "newer_than:5y from:tldrnewsletter.com",
    "from:(dan@tldrnewsletter.com OR hello@tldrnewsletter.com OR team@tldrnewsletter.com OR news@tldrnewsletter.com)",
    "subject:TLDR newer_than:5y",
]


async def estimate(svc, q: str) -> int | str:
    try:
        r = await _gmail_execute(
            svc, svc.users().messages().list(userId="me", q=q, maxResults=1)
        )
        return int(r.get("resultSizeEstimate") or 0)
    except Exception as e:
        return f"ERR {e}"


async def main(email: str) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        imported = (
            await db.execute(
                select(func.count())
                .select_from(Issue)
                .join(Newsletter)
                .where(
                    Newsletter.user_id == u.id,
                    or_(
                        Newsletter.name.ilike("%tldr%"),
                        Newsletter.sender_email.ilike("%tldr%"),
                    ),
                )
            )
        ).scalar() or 0
        print(f"DB imported TLDR issues: {imported}", flush=True)

        svc = get_gmail_service(u)
        for q in QUERIES:
            n = await estimate(svc, q)
            print(f"  ~{n}  q={q}", flush=True)

        print("Collecting unique IDs with broad queries (cap 20000)...", flush=True)
        ids = await _collect_message_ids(
            svc,
            [
                "in:anywhere from:tldrnewsletter.com",
                "in:anywhere from:tldr.tech",
                "from:tldrnewsletter.com",
                "from:tldr.tech",
                "list:tldrnewsletter.com",
                "newer_than:5y from:tldrnewsletter.com",
            ],
            20000,
        )
        print(f"Unique TLDR Gmail message IDs found: {len(ids)}", flush=True)

        # How many already in DB?
        existing = set(
            (
                await db.execute(
                    select(Issue.gmail_message_id)
                    .join(Newsletter)
                    .where(Newsletter.user_id == u.id, Issue.gmail_message_id.in_(ids))
                )
            ).scalars().all()
        )
        missing = [i for i in ids if i not in existing]
        print(f"Already in DB: {len(existing)}", flush=True)
        print(f"MISSING to import: {len(missing)}", flush=True)


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "krsgupta@ucdavis.edu"
    asyncio.run(main(email))
