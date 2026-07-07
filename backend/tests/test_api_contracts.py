"""API contract and import smoke tests."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_openapi_schema():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema.get("paths", {})
    assert "/api/v1/knowledge/connectors" in paths
    assert "/api/v1/knowledge/prompts" in paths
    assert "/api/v1/intelligence/events/{event_id}" in paths
    assert "/api/v1/ops/pipeline" in paths


def test_knowledge_routes_require_auth():
    resp = client.get("/api/v1/knowledge/connectors")
    assert resp.status_code in (401, 403)
