"""Gmail source connector — wraps existing gmail_sync."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import DiscoveredSource, FetchedItem, SourceConnector
from app.models.newsletter import Newsletter
from app.models.user import User
from app.services.gmail_sync import incremental_sync, initial_sync


class GmailConnector(SourceConnector):
    source_type = "gmail"

    def __init__(self, db: AsyncSession, user: User):
        self.db = db
        self.user = user

    async def discover(self) -> list[DiscoveredSource]:
        result = await self.db.execute(
            select(Newsletter).where(Newsletter.user_id == self.user.id)
        )
        return [
            DiscoveredSource(
                name=n.name,
                identifier=n.sender_email,
                source_type="gmail",
                metadata={"issue_count": n.issue_count, "domain": n.domain},
            )
            for n in result.scalars().all()
        ]

    async def fetch(self, source_id: str, since: datetime | None = None) -> list[FetchedItem]:
        # Items are imported via gmail_sync.process_message — return empty;
        # fetch is handled during sync for Gmail's incremental model.
        return []

    async def sync(self, user_id: str) -> dict:
        if not self.user.initial_sync_complete:
            return await initial_sync(self.db, self.user)
        return await incremental_sync(self.db, self.user)
