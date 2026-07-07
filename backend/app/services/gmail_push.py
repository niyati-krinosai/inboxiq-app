"""Gmail Push Notifications — real-time sync via Pub/Sub webhook."""

import base64
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import get_logger
from app.models.operations import GmailWatch
from app.models.user import User
from app.services.google_oauth import get_gmail_service

settings = get_settings()
log = get_logger(__name__)


async def register_gmail_watch(db: AsyncSession, user: User) -> dict:
    """Register Gmail push notifications for a user."""
    if not settings.gmail_pubsub_topic:
        return {"status": "disabled", "reason": "GMAIL_PUBSUB_TOPIC not configured"}

    service = get_gmail_service(user)
    body = {"topicName": settings.gmail_pubsub_topic, "labelIds": ["INBOX"]}
    result = service.users().watch(userId="me", body=body).execute()

    expiration_ms = int(result.get("expiration", 0))
    expiration = datetime.fromtimestamp(expiration_ms / 1000, tz=timezone.utc) if expiration_ms else None

    existing = await db.execute(select(GmailWatch).where(GmailWatch.user_id == user.id))
    watch = existing.scalar_one_or_none()
    if watch:
        watch.history_id = str(result.get("historyId", ""))
        watch.expiration = expiration
        watch.topic_name = settings.gmail_pubsub_topic
    else:
        watch = GmailWatch(
            user_id=user.id,
            history_id=str(result.get("historyId", "")),
            expiration=expiration,
            topic_name=settings.gmail_pubsub_topic,
        )
        db.add(watch)

    await db.flush()
    log.info("gmail_watch_registered", user_id=str(user.id), expiration=str(expiration))
    return {"status": "registered", "history_id": watch.history_id, "expiration": expiration}


async def handle_pubsub_notification(db: AsyncSession, envelope: dict) -> dict:
    """Process Gmail Pub/Sub push notification."""
    message = envelope.get("message", {})
    data_b64 = message.get("data", "")
    if not data_b64:
        return {"status": "ignored", "reason": "no data"}

    payload = json.loads(base64.urlsafe_b64decode(data_b64))
    email = payload.get("emailAddress")
    history_id = str(payload.get("historyId", ""))

    if not email:
        return {"status": "ignored", "reason": "no email"}

    result = await db.execute(select(User).where(User.email == email, User.gmail_connected == True))  # noqa: E712
    user = result.scalar_one_or_none()
    if not user:
        return {"status": "ignored", "reason": "user not found"}

    user.gmail_history_id = history_id
    await db.flush()

    from app.workers.tasks import sync_user_gmail
    sync_user_gmail.delay(str(user.id))

    log.info("gmail_push_received", user_id=str(user.id), history_id=history_id)
    return {"status": "sync_triggered", "user_id": str(user.id)}
