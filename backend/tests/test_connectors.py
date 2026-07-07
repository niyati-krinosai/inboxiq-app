"""Connector plugin architecture tests."""

from app.connectors import CONNECTOR_REGISTRY
from app.connectors.base import SourceConnector


def test_connector_registry():
    assert "gmail" in CONNECTOR_REGISTRY
    assert "rss" in CONNECTOR_REGISTRY
    assert "github" in CONNECTOR_REGISTRY
    for name, cls in CONNECTOR_REGISTRY.items():
        assert issubclass(cls, SourceConnector), f"{name} must extend SourceConnector"
