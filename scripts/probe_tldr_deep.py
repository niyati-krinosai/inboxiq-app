"""Deep probe: find TLDR-like mail that may not be from tldrnewsletter.com."""
import asyncio
import collections
import os
import sys
from email.utils import parseaddr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.gmail_sync import _collect_message_ids, _gmail_execute
from app.services.google_oauth import get_gmail_service

EXTRA_QUERIES = [
    'subject:"TLDR AI"',
    'subject:"TLDR Marketing"',
    'subject:"TLDR Dev"',
    'subject:"TLDR Founders"',
    'subject:"TLDR"',
    "from:(TLDR)",
    '"tldrnewsletter"',
    "unsubscribe tldr",
]


async def main(email: str) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        svc = get_gmail_service(u)

        print("Collecting broad subject/from TLDR candidates (cap 5000)...", flush=True)
        ids = await _collect_message_ids(svc, EXTRA_QUERIES, 5000)
        print(f"Candidate IDs: {len(ids)}", flush=True)

        senders = collections.Counter()
        domains = collections.Counter()
        products = collections.Counter()
        sample_non_tldr = []

        for i, mid in enumerate(ids):
            msg = await _gmail_execute(
                svc,
                svc.users().messages().get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "List-Id", "List-Unsubscribe"],
                ),
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            frm = headers.get("from", "")
            name, addr = parseaddr(frm)
            senders[frm] += 1
            domain = addr.split("@")[-1].lower() if "@" in addr else "?"
            domains[domain] += 1
            if name:
                products[name.strip()] += 1
            if "tldr" not in domain and "tldr" not in frm.lower():
                if len(sample_non_tldr) < 15:
                    sample_non_tldr.append((frm, headers.get("subject", "")[:80]))
            if (i + 1) % 100 == 0:
                print(f"  scanned {i+1}/{len(ids)}", flush=True)

        print("\nDOMAINS:", flush=True)
        for k, v in domains.most_common(20):
            print(f"  {v:5d}  {k}", flush=True)
        print("\nFROM (top 30):", flush=True)
        for k, v in senders.most_common(30):
            print(f"  {v:5d}  {k}", flush=True)
        print("\nDISPLAY NAMES (top 30):", flush=True)
        for k, v in products.most_common(30):
            print(f"  {v:5d}  {k}", flush=True)
        if sample_non_tldr:
            print("\nNon-tldr-domain samples:", flush=True)
            for frm, subj in sample_non_tldr:
                print(f"  FROM={frm} | SUBJ={subj}", flush=True)


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "krsgupta@ucdavis.edu"
    asyncio.run(main(email))
