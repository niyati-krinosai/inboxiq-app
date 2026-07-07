"""Stub connectors for future sources — same pipeline, different ingestion."""

from datetime import datetime

from app.connectors.base import DiscoveredSource, FetchedItem, SourceConnector


class RSSConnector(SourceConnector):
    source_type = "rss"

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch(self, source_id: str, since: datetime | None = None) -> list[FetchedItem]:
        return []

    async def sync(self, user_id: str) -> dict:
        return {"status": "not_implemented", "source": "rss"}


class GitHubReleasesConnector(SourceConnector):
    source_type = "github"

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch(self, source_id: str, since: datetime | None = None) -> list[FetchedItem]:
        return []

    async def sync(self, user_id: str) -> dict:
        return {"status": "not_implemented", "source": "github"}


class HackerNewsConnector(SourceConnector):
    source_type = "hackernews"

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch(self, source_id: str, since: datetime | None = None) -> list[FetchedItem]:
        return []

    async def sync(self, user_id: str) -> dict:
        return {"status": "not_implemented", "source": "hackernews"}


class ArxivConnector(SourceConnector):
    source_type = "arxiv"

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch(self, source_id: str, since: datetime | None = None) -> list[FetchedItem]:
        return []

    async def sync(self, user_id: str) -> dict:
        return {"status": "not_implemented", "source": "arxiv"}
