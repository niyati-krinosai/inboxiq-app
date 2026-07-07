"""Plugin architecture — generic source connectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DiscoveredSource:
    name: str
    identifier: str  # email, feed URL, repo path
    source_type: str  # gmail|rss|github|hackernews
    metadata: dict | None = None


@dataclass
class FetchedItem:
    external_id: str
    subject: str | None
    html: str | None
    text: str | None
    sender: str | None
    received_at: datetime
    headers: dict | None = None


class SourceConnector(ABC):
    """Generic ingestion interface — pipeline unchanged regardless of source."""

    source_type: str = "unknown"

    @abstractmethod
    async def discover(self) -> list[DiscoveredSource]:
        """Find available sources for this connector."""
        ...

    @abstractmethod
    async def fetch(self, source_id: str, since: datetime | None = None) -> list[FetchedItem]:
        """Fetch new items from a source."""
        ...

    @abstractmethod
    async def sync(self, user_id: str) -> dict:
        """Full sync — discover + fetch + queue for pipeline."""
        ...
