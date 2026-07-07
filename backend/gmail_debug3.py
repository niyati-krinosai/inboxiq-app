import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.google_oauth import get_gmail_service
from app.services.gmail_sync import discover_and_import_messages, initial_sync
from app.services.newsletter_registry import detect_and_classify

async def main():
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        print("USER", user.email if user else "none")
        svc = get_gmail_service(user)
        resp = svc.users().messages().list(userId='me', maxResults=10).execute()
        ids = [m['id'] for m in resp.get('messages', [])]
        print('TOTAL msgs from Gmail list', len(ids), ids)
        for msg_id in ids:
            msg = svc.users().messages().get(userId='me', id=msg_id, format='full').execute()
            headers = msg.get('payload', {}).get('headers', [])
            header_map = {h['name'].lower(): h['value'] for h in headers}
            from_header = header_map.get('from', '')
            subject = header_map.get('subject', '')
            print('---')
            print('id', msg_id)
            print('from', from_header)
            print('subject', subject)
            for key in ['list-unsubscribe', 'list-id', 'precedence', 'auto-submitted', 'feedback-id', 'x-mailer', 'x-campaign', 'x-mailgun-tag', 'x-sg-eid']:
                if key in header_map:
                    print(key, header_map[key])
            det = detect_and_classify([{'name': h['name'], 'value': h['value']} for h in headers], from_header)
            print('detect', det)
            if det:
                print('  is_newsletter', det.is_newsletter, 'confidence', det.confidence, 'signals', det.signals, 'sender', det.sender_email, 'name', det.sender_name, 'domain', det.domain)
            else:
                print('  REJECTED')
        print('NOW RUNNING direct import on first 3 msgs')
        results = await discover_and_import_messages(db, user, ids[:3])
        print('DISCOVER IMPORT RESULTS', results)
        print('NOW running initial_sync')
        user.initial_sync_complete = False
        await db.flush()
        result_init = await initial_sync(db, user)
        print('INITIAL_SYNC RESULT', result_init)
        print('user gmail_history_id', user.gmail_history_id, 'initial_sync_complete', user.initial_sync_complete)

asyncio.run(main())
