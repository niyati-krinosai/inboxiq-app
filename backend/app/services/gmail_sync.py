import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import GMAIL_NEWSLETTER_FROM_CLAUSES
from app.core.logging import get_logger
from app.core.rate_limit import gmail_limiter
from app.models.issue import PIPELINE_IMPORTED, Issue
from app.models.newsletter import Newsletter
from app.models.user import User
from app.core.pipeline_tracer import trace_stage
from app.services.google_oauth import build_credentials, get_gmail_service
from app.services.newsletter_registry import (
    detect_and_classify,
    register_newsletter,
    update_newsletter_frequency,
)

settings = get_settings()
log = get_logger(__name__)


def _decode_body_data(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _extract_html_from_payload(payload: dict) -> str:
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")

    if mime_type == "text/html" and data:
        return _decode_body_data(data)

    for part in payload.get("parts", []):
        html = _extract_html_from_payload(part)
        if html:
            return html

    if mime_type == "text/plain" and data:
        return _decode_body_data(data)

    return ""


def _parse_message_date(internal_date_ms: str | None, date_header: str) -> datetime:
    if date_header:
        try:
            return parsedate_to_datetime(date_header).astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass
    if internal_date_ms:
        return datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


async def _gmail_execute(service, request):
    await gmail_limiter.acquire()
    return request.execute()


async def _collect_message_ids(service, queries: list[str], max_messages: int) -> list[str]:
    """Run multiple Gmail searches and dedupe message IDs (newest first)."""
    seen: set[str] = set()
    ordered: list[str] = []

    for query in queries:
        page_token = None
        while len(ordered) < max_messages:
            response = await _gmail_execute(
                service,
                service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=min(100, max_messages - len(ordered)),
                    pageToken=page_token,
                ),
            )
            for item in response.get("messages", []):
                msg_id = item["id"]
                if msg_id not in seen:
                    seen.add(msg_id)
                    ordered.append(msg_id)
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return ordered[:max_messages]


def _discovery_queries() -> list[str]:
    """Queries that surface newsletter subscriptions in Gmail."""
    return [
        f"list:({{list-unsubscribe}} OR unsubscribe) OR from:({GMAIL_NEWSLETTER_FROM_CLAUSES})",
        f"from:({GMAIL_NEWSLETTER_FROM_CLAUSES}) newer_than:90d",
        "from:(tldrnewsletter.com OR tldr.tech) newer_than:30d",
    ]


async def import_message(
    db: AsyncSession,
    user: User,
    service,
    message_id: str,
) -> Issue | None:
    """Phase 3: import raw newsletter issue only — no cleaning, no AI."""
    async with trace_stage(db, user.id, "discovery", retry_count=0):
        pass

    async with trace_stage(
        db, user.id, "import",
        retry_count=0,
    ) as tracer:
        msg = await _gmail_execute(
            service,
            service.users().messages().get(userId="me", id=message_id, format="full"),
        )

    headers = msg.get("payload", {}).get("headers", [])
    header_list = [{"name": h["name"], "value": h["value"]} for h in headers]
    header_map = {h["name"].lower(): h["value"] for h in headers}

    from_header = header_map.get("from", "")
    detection = detect_and_classify(header_list, from_header)
    if not detection:
        return None

    received_at = _parse_message_date(msg.get("internalDate"), header_map.get("date", ""))
    newsletter = await register_newsletter(db, user.id, detection, received_at)

    existing = await db.execute(
        select(Issue).where(
            Issue.newsletter_id == newsletter.id,
            Issue.gmail_message_id == message_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    html = _extract_html_from_payload(msg.get("payload", {}))

    issue = Issue(
        newsletter_id=newsletter.id,
        gmail_message_id=message_id,
        subject=header_map.get("subject", ""),
        sender_email=detection.sender_email,
        sender_name=detection.sender_name or None,
        headers_json=header_map,
        raw_html=html,
        received_at=received_at,
        published_at=received_at,
        processing_status=PIPELINE_IMPORTED,
    )
    db.add(issue)
    newsletter.issue_count += 1
    newsletter.last_sync_at = datetime.now(timezone.utc)
    newsletter.processing_status = "syncing"
    await db.flush()

    async with trace_stage(
        db, user.id, "import",
        issue_id=issue.id, newsletter_id=newsletter.id,
    ):
        pass

    async with trace_stage(db, user.id, "discovery", newsletter_id=newsletter.id):
        pass

    log.info(
        "issue_imported",
        issue_id=str(issue.id),
        newsletter=newsletter.name,
        message_id=message_id,
    )
    return issue


async def discover_and_import_messages(
    db: AsyncSession,
    user: User,
    message_ids: list[str],
) -> dict[str, Any]:
    service = get_gmail_service(user)
    imported = 0
    scanned = 0

    for msg_id in message_ids:
        scanned += 1
        try:
            issue = await import_message(db, user, service, msg_id)
            if issue:
                imported += 1
        except Exception as e:
            log.warning("import_failed", message_id=msg_id, error=str(e))

    # Update frequency for all newsletters touched
    result = await db.execute(select(Newsletter).where(Newsletter.user_id == user.id))
    for newsletter in result.scalars().all():
        await update_newsletter_frequency(db, newsletter)
        newsletter.processing_status = "completed"

    return {"scanned": scanned, "imported": imported}


async def initial_sync(db: AsyncSession, user: User) -> dict[str, Any]:
    """Phase 3: historical import of all detected newsletter issues."""
    user.sync_status = "syncing"
    service = get_gmail_service(user)

    profile = await _gmail_execute(service, service.users().getProfile(userId="me"))
    history_id = profile.get("historyId")

    # Broad discovery — multiple queries so TLDR and similar senders are not missed
    messages = await _collect_message_ids(
        service,
        _discovery_queries(),
        settings.initial_sync_max_messages,
    )

    result = await discover_and_import_messages(db, user, messages)

    user.gmail_history_id = str(history_id)
    user.initial_sync_complete = True
    user.last_sync_at = datetime.now(timezone.utc)
    user.sync_status = "idle"
    await db.flush()
    # Persist any refreshed OAuth tokens
    await db.flush()

    log.info("initial_sync_complete", user_id=str(user.id), **result)
    return {**result, "history_id": history_id, "messages_found": len(messages)}


async def incremental_sync(db: AsyncSession, user: User) -> dict[str, Any]:
    """Phase 14: History API — only new messages since last sync."""
    if not user.gmail_history_id:
        return await initial_sync(db, user)

    user.sync_status = "syncing"
    service = get_gmail_service(user)
    start_history_id = user.gmail_history_id
    new_message_ids: list[str] = []

    try:
        response = await _gmail_execute(
            service,
            service.users().history().list(
                userId="me",
                startHistoryId=start_history_id,
                historyTypes=["messageAdded"],
            ),
        )
    except Exception as e:
        if "404" in str(e) or "historyId" in str(e).lower():
            log.warning("history_id_expired", user_id=str(user.id))
            return await initial_sync(db, user)
        user.sync_status = "failed"
        raise

    for record in response.get("history", []):
        for added in record.get("messagesAdded", []):
            msg_id = added.get("message", {}).get("id")
            if msg_id:
                new_message_ids.append(msg_id)

    result = await discover_and_import_messages(db, user, new_message_ids)

    # Catch newsletters (e.g. TLDR) that history sync may have missed historically
    supplemental_ids = await _collect_message_ids(
        service,
        ["from:(tldrnewsletter.com OR tldr.tech) newer_than:30d"],
        100,
    )
    extra = [m for m in supplemental_ids if m not in set(new_message_ids)]
    if extra:
        supp = await discover_and_import_messages(db, user, extra)
        result["imported"] = result.get("imported", 0) + supp.get("imported", 0)
        result["scanned"] = result.get("scanned", 0) + supp.get("scanned", 0)

    user.gmail_history_id = str(response.get("historyId", start_history_id))
    user.last_sync_at = datetime.now(timezone.utc)
    user.sync_status = "idle"
    await db.flush()

    log.info("incremental_sync_complete", user_id=str(user.id), new_messages=len(new_message_ids), **result)
    return {**result, "new_messages": len(new_message_ids)}
