"""Trigger Gmail sync on production Render API for a user by email.

Needs production DATABASE_URL + JWT_SECRET_KEY (from Render inboxiq-api Environment).
"""
import argparse
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.auth import create_access_token

API_BASE = os.environ.get("INBOXIQ_API_URL", "https://inboxiq-api.onrender.com/api/v1")


async def main(email: str) -> None:
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: Set DATABASE_URL")
        sys.exit(1)
    if not os.environ.get("JWT_SECRET_KEY"):
        print("ERROR: Set JWT_SECRET_KEY from Render inboxiq-api Environment")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            print(f"No user: {email}")
            sys.exit(1)
        token = create_access_token(user.id, user.email)

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=600.0) as client:
        print("Triggering sync on Render (may take several minutes)...")
        r = await client.post(f"{API_BASE}/sync/trigger", headers=headers)
        print("sync/trigger:", r.status_code, r.text)
        if r.status_code == 200 and "sync_complete" in r.text:
            print("Gmail import finished on server.")
            return
        r2 = await client.post(f"{API_BASE}/sync/process", headers=headers)
        print("sync/process:", r2.status_code, r2.text)

    print("Poll with: python scripts/list_users.py", email.split("@")[0])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    asyncio.run(main(p.parse_args().email))
