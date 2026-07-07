"""OAuth flow tests — must pass before every release."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials

from app.main import app
from app.services.auth import create_access_token, decode_access_token
from app.services.google_oauth import decode_oauth_state, get_authorization_url
import uuid


client = TestClient(app)


def test_login_url_has_no_pkce():
    with patch("app.api.routes.get_authorization_url", wraps=get_authorization_url):
        resp = client.get("/api/v1/auth/login")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert "code_challenge" not in data["auth_url"]
    assert decode_oauth_state(data["state"])


def test_oauth_callback_success_redirects_with_token():
    creds = Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="secret",
        scopes=["openid", "email"],
    )
    auth = get_authorization_url()
    with patch("app.api.routes.exchange_code_for_tokens", return_value=(creds, "id.jwt.token")), \
         patch("app.api.routes.get_user_info", return_value={
             "id": "google-123",
             "email": "user@example.com",
             "name": "User",
             "picture": None,
         }), \
         patch("app.api.routes.sync_user_gmail") as mock_sync:
        mock_sync.delay = MagicMock(side_effect=Exception("no celery"))
        resp = client.get(
            "/api/v1/auth/callback",
            params={"code": "auth-code", "state": auth["state"]},
            follow_redirects=False,
        )
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith("http://localhost:3000/auth/callback?token=")
    assert "error" not in location


def test_oauth_callback_bad_state_redirects_with_error():
    resp = client.get(
        "/api/v1/auth/callback",
        params={"code": "auth-code", "state": "invalid-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert "error=" in resp.headers["location"]


def test_jwt_roundtrip():
    uid = uuid.uuid4()
    token = create_access_token(uid, "user@example.com")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == str(uid)
    assert payload["email"] == "user@example.com"
