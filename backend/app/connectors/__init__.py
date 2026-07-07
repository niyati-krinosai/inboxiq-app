"""Source connector registry."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import SourceConnector
from app.connectors.gmail_connector import GmailConnector
from app.connectors.stubs import ArxivConnector, GitHubReleasesConnector, HackerNewsConnector, RSSConnector
from app.models.user import User

CONNECTOR_REGISTRY: dict[str, type] = {
    "gmail": GmailConnector,
    "rss": RSSConnector,
    "github": GitHubReleasesConnector,
    "hackernews": HackerNewsConnector,
    "arxiv": ArxivConnector,
}


def get_connector(source_type: str, db: AsyncSession, user: User) -> SourceConnector:
    cls = CONNECTOR_REGISTRY.get(source_type)
    if not cls:
        raise ValueError(f"Unknown connector: {source_type}")
    return cls(db, user)
