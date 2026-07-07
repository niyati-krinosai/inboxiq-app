import asyncio
import traceback
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.gmail_sync import discover_and_import_messages
from app.services.google_oauth import get_gmail_service

async def main():
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        if not user:
            raise SystemExit('no user found')
        service = get_gmail_service(user)
        resp = service.users().messages().list(userId='me', maxResults=3).execute()
        ids = [m['id'] for m in resp.get('messages', [])]
        print('ids', ids)
        try:
            result = await discover_and_import_messages(db, user, ids)
            print('result', result)
        except Exception:
            traceback.print_exc()

asyncio.run(main())
