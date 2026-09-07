"""List every distinct TLDR product display-name in a user's Gmail vs DB."""
import asyncio
import collections
import os
import sys
from email.utils import parseaddr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import or_, select

from app.database import AsyncSessionLocal
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.gmail_sync import _collect_message_ids, _gmail_execute
from app.services.google_oauth import get_gmail_service


async def main(email: str) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db_names = set(
            (
                await db.execute(
                    select(Newsletter.name).where(
                        Newsletter.user_id == u.id,
                        or_(
                            Newsletter.name.ilike("%tldr%"),
                            Newsletter.sender_email.ilike("%tldr%"),
                        ),
                    )
                )
            ).scalars().all()
        )
        print("IN DB:", sorted(db_names), flush=True)

        svc = get_gmail_service(u)
        ids = await _collect_message_ids(
            svc,
            [
                "in:anywhere from:tldrnewsletter.com",
                "in:anywhere from:tldr.tech",
                "in:anywhere from:dan@tldrnewsletter.com",
            ],
            20000,
        )
        print(f"gmail ids: {len(ids)}", flush=True)

        products: collections.Counter[str] = collections.Counter()
        for i, mid in enumerate(ids):
            msg = await _gmail_execute(
                svc,
                svc.users().messages().get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From"],
                ),
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            name, _ = parseaddr(headers.get("from", ""))
            name = (name or "").strip().strip('"')
            products[name or "(empty)"] += 1
            if (i + 1) % 200 == 0:
                print(f"scanned {i+1}", flush=True)

        print("\nALL TLDR PRODUCTS IN GMAIL:", flush=True)
        missing = []
        for name, count in products.most_common():
            flag = "OK" if name in db_names else "MISSING"
            if flag == "MISSING" and name != "(empty)":
                missing.append(name)
            print(f"  [{flag}] {count:4d}  {name}", flush=True)

        print("\nNOT IN DB YET:", missing, flush=True)
        print(f"Total distinct products in Gmail: {len(products)}", flush=True)


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "krsgupta@ucdavis.edu"
    asyncio.run(main(email))
