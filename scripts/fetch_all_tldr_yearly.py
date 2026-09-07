"""Fetch ALL TLDR mail year-by-year (avoids Gmail single-query caps), import missing only."""
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


def _year_queries(start_year: int, end_year: int) -> list[str]:
    qs = []
    for y in range(start_year, end_year + 1):
        qs.append(f"in:anywhere from:tldrnewsletter.com after:{y}/01/01 before:{y+1}/01/01")
        qs.append(f"in:anywhere from:tldr.tech after:{y}/01/01 before:{y+1}/01/01")
        qs.append(f'in:anywhere subject:"TLDR" after:{y}/01/01 before:{y+1}/01/01')
    qs.extend(
        [
            "in:anywhere from:tldrnewsletter.com",
            "in:anywhere from:tldr.tech",
            "in:anywhere from:dan@tldrnewsletter.com",
        ]
    )
    return qs


async def _tldr_stats(db, user_id) -> dict:
    nls = list(
        (
            await db.execute(
                select(Newsletter)
                .where(Newsletter.user_id == user_id)
                .where(
                    or_(
                        Newsletter.name.ilike("%tldr%"),
                        Newsletter.sender_email.ilike("%tldr%"),
                    )
                )
                .order_by(Newsletter.name)
            )
        ).scalars().all()
    )
    rows = []
    total = 0
    for n in nls:
        c = (await db.execute(select(func.count()).where(Issue.newsletter_id == n.id))).scalar() or 0
        total += c
        rows.append((n.name, c))
    return {"products": rows, "issues": total, "products_n": len(rows)}


async def main(email: str, start_year: int, end_year: int) -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user.gmail_connected = True
        user.sync_status = "syncing"
        await db.commit()

        before = await _tldr_stats(db, user.id)
        print("BEFORE:", before, flush=True)

        svc = get_gmail_service(user)
        queries = _year_queries(start_year, end_year)
        print(f"Collecting across {len(queries)} queries ({start_year}-{end_year})...", flush=True)
        ids = await _collect_message_ids(svc, queries, 50000)
        print(f"Unique Gmail IDs: {len(ids)}", flush=True)

        existing = set(
            (
                await db.execute(
                    select(Issue.gmail_message_id)
                    .join(Newsletter)
                    .where(Newsletter.user_id == user.id, Issue.gmail_message_id.in_(ids))
                )
            ).scalars().all()
        )
        # Also check any issue for this user with those ids (in case not under tldr nl yet)
        existing |= set(
            (
                await db.execute(
                    select(Issue.gmail_message_id)
                    .join(Newsletter)
                    .where(Newsletter.user_id == user.id)
                )
            ).scalars().all()
        )
        missing = [i for i in ids if i not in existing]
        print(f"Already imported (any newsletter): {len(ids) - len(missing)}", flush=True)
        print(f"MISSING to import: {len(missing)}", flush=True)

        if missing:
            user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
            # Import in chunks with commits to avoid connection drops
            chunk = 50
            imported_total = 0
            for i in range(0, len(missing), chunk):
                batch = missing[i : i + chunk]
                user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
                res = await discover_and_import_messages(db, user, batch)
                await db.commit()
                imported_total += res.get("imported", 0)
                print(
                    f"  chunk {i//chunk + 1}: scanned={res.get('scanned')} imported={res.get('imported')} total_imported={imported_total}",
                    flush=True,
                )
        else:
            print("Nothing missing — Gmail TLDR set already fully imported.", flush=True)

        # Process any newly imported issues into articles
        for i in range(30):
            pipe = await run_light_pipeline_batch(db, user.id, limit=200)
            await db.commit()
            print(f"Pipeline {i+1}: {pipe}", flush=True)
            if pipe.get("processed", 0) == 0:
                break

        user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        user.sync_status = "idle"
        await db.commit()

        after = await _tldr_stats(db, user.id)
        arts = (await db.execute(select(func.count()).where(Article.user_id == user.id))).scalar() or 0
        print("AFTER:", after, flush=True)
        print("articles_total:", arts, flush=True)
        print("DONE", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", default="krsgupta@ucdavis.edu")
    p.add_argument("--start-year", type=int, default=2019)
    p.add_argument("--end-year", type=int, default=2026)
    args = p.parse_args()
    asyncio.run(main(args.email, args.start_year, args.end_year))
