"""Split lumped TLDR issues into per-product newsletters (bulk, fast)."""
import asyncio
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, or_, select, update

from app.database import AsyncSessionLocal
from app.models.issue import Issue
from app.models.newsletter import Newsletter
from app.models.user import User


def _product_name(issue: Issue) -> str:
    if issue.sender_name and "tldr" in issue.sender_name.lower():
        return issue.sender_name.strip()
    headers = issue.headers_json or {}
    from_hdr = headers.get("from") or headers.get("From") or ""
    m = re.match(r"^([^<]+)<", from_hdr.strip())
    if m:
        name = m.group(1).strip().strip('"')
        if "tldr" in name.lower():
            return name
    return "TLDR"


def _storage_email(name: str, domain: str = "tldrnewsletter.com") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tldr"
    return f"{slug}@{domain}"


async def main(email: str) -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        tldr_nls = list(
            (
                await db.execute(
                    select(Newsletter).where(
                        Newsletter.user_id == user.id,
                        or_(
                            Newsletter.name.ilike("%tldr%"),
                            Newsletter.sender_email.ilike("%tldr%"),
                            Newsletter.domain.ilike("%tldr%"),
                        ),
                    )
                )
            ).scalars().all()
        )
        print("Before:", flush=True)
        for n in tldr_nls:
            c = (await db.execute(select(func.count()).where(Issue.newsletter_id == n.id))).scalar() or 0
            print(f"  {n.name} | {n.sender_email} | issues={c}", flush=True)

        nl_ids = [n.id for n in tldr_nls]
        issues = list(
            (await db.execute(select(Issue).where(Issue.newsletter_id.in_(nl_ids)))).scalars().all()
        )
        print(f"Loaded {len(issues)} issues", flush=True)

        by_product: dict[str, list] = defaultdict(list)
        for issue in issues:
            by_product[_product_name(issue)].append(issue)

        existing = {n.name: n for n in tldr_nls}
        for product, group in by_product.items():
            if product in existing:
                continue
            n = Newsletter(
                user_id=user.id,
                name=product,
                sender_email=_storage_email(product),
                sender_name=product,
                domain="tldrnewsletter.com",
                first_seen_at=min(i.received_at for i in group),
                last_seen_at=max(i.received_at for i in group),
                issue_count=0,
                article_count=0,
                processing_status="completed",
            )
            db.add(n)
            existing[product] = n
            print(f"  create {product}", flush=True)
        await db.flush()

        moved = 0
        for product, group in by_product.items():
            target = existing[product]
            ids = [i.id for i in group if i.newsletter_id != target.id]
            if not ids:
                continue
            await db.execute(
                update(Issue).where(Issue.id.in_(ids)).values(newsletter_id=target.id)
            )
            moved += len(ids)
            print(f"  move {len(ids)} -> {product}", flush=True)

        # Fix storage emails + counts
        for name, n in existing.items():
            c = (await db.execute(select(func.count()).where(Issue.newsletter_id == n.id))).scalar() or 0
            n.issue_count = c
            if n.sender_email == "dan@tldrnewsletter.com" or "@tldrnewsletter.com" not in (n.sender_email or ""):
                desired = _storage_email(name)
                clash = (
                    await db.execute(
                        select(Newsletter).where(
                            Newsletter.user_id == user.id,
                            Newsletter.sender_email == desired,
                            Newsletter.id != n.id,
                        )
                    )
                ).scalar_one_or_none()
                if clash is None:
                    n.sender_email = desired

        await db.commit()
        print(f"Moved {moved}", flush=True)
        print("After:", flush=True)
        for name in sorted(existing):
            n = existing[name]
            print(f"  {n.name} | {n.sender_email} | issues={n.issue_count}", flush=True)


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "krsgupta@ucdavis.edu"
    asyncio.run(main(email))
