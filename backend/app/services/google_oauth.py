import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token as google_id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import get_logger
from app.models.user import User
from app.services.encryption import decrypt_token, encrypt_token

settings = get_settings()
log = get_logger(__name__)


def _oauth_client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def create_oauth_flow() -> Flow:
    """Confidential web client — PKCE disabled (client_secret used instead)."""
    return Flow.from_client_config(
        _oauth_client_config(),
        scopes=settings.gmail_scopes,
        redirect_uri=settings.google_redirect_uri,
        autogenerate_code_verifier=False,
    )


def _create_oauth_state() -> str:
    """CSRF state token returned by Google on callback."""
    expire = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
    payload = {
        "nonce": secrets.token_urlsafe(16),
        "exp": expire,
        "purpose": "oauth",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_oauth_state(state: str) -> dict:
    if not state:
        raise ValueError("Missing OAuth state — please sign in again")
    try:
        payload = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Sign-in session expired — please try again") from exc
    if payload.get("purpose") != "oauth":
        raise ValueError("Invalid OAuth state")
    return payload


def verify_oauth_state(state: str) -> bool:
    try:
        decode_oauth_state(state)
        return True
    except ValueError:
        return False


def get_authorization_url() -> dict:
    state = _create_oauth_state()
    flow = create_oauth_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    if "code_challenge" in auth_url:
        raise RuntimeError("OAuth misconfigured: PKCE must be disabled for this client")
    return {"auth_url": auth_url, "state": state}


def _validate_scopes(granted_scopes: list[str] | None) -> None:
    if not granted_scopes:
        return
    granted = set(granted_scopes)
    forbidden = {
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.send",
        "https://mail.google.com/",
    }
    if granted & forbidden:
        raise ValueError("Forbidden Gmail scopes requested — read-only only")


def _normalize_expiry(expiry: datetime | None) -> datetime | None:
    if not expiry:
        return None
    if expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc)
    return expiry.replace(tzinfo=None)


def exchange_code_for_tokens(code: str, state: str | None = None) -> tuple[Credentials, str | None]:
    """Exchange auth code for credentials. Returns (credentials, id_token|None)."""
    decode_oauth_state(state or "")

    token_uri = _oauth_client_config()["web"]["token_uri"]
    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }

    resp = requests.post(token_uri, data=payload, timeout=15)
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:200]}

    safe_body = {
        k: ("[REDACTED]" if k in ("access_token", "refresh_token", "id_token") else v)
        for k, v in body.items()
    }
    log.info("oauth_token_endpoint_response", status=resp.status_code, body=safe_body)

    if resp.status_code != 200:
        detail = body.get("error_description") or body.get("error") or "Google sign-in failed"
        raise ValueError(detail)

    token = body.get("access_token")
    if not token:
        raise ValueError("Google did not return an access token")

    id_token = body.get("id_token")
    scope_val = body.get("scope")
    if isinstance(scope_val, str):
        scopes = scope_val.split()
    elif isinstance(scope_val, list):
        scopes = scope_val
    else:
        scopes = None

    credentials = Credentials(
        token=token,
        refresh_token=body.get("refresh_token"),
        token_uri=token_uri,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=scopes or settings.gmail_scopes,
    )
    expires_in = body.get("expires_in")
    if expires_in:
        try:
            credentials.expiry = _normalize_expiry(
                datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            )
        except Exception:
            pass
    if getattr(credentials, "expiry", None) is not None:
        credentials.expiry = _normalize_expiry(credentials.expiry)

    _validate_scopes(list(credentials.scopes or []))
    return credentials, id_token


def get_user_info(credentials: Credentials, id_token: str | None = None) -> dict:
    """Fetch profile from verified ID token or Google API."""
    if id_token:
        try:
            verified = google_id_token.verify_oauth2_token(
                id_token, Request(), settings.google_client_id
            )
            return {
                "id": verified["sub"],
                "email": verified["email"],
                "name": verified.get("name"),
                "picture": verified.get("picture"),
            }
        except Exception as exc:
            log.warning("oauth_id_token_decode_failed", reason=str(exc))

    try:
        oauth2 = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
        return oauth2.userinfo().get().execute()
    except Exception as exc:
        log.error("oauth_userinfo_failed", error=str(exc))
        raise ValueError("Could not load your Google profile. Try signing in again.") from exc


def store_credentials(user: User, credentials: Credentials) -> None:
    user.access_token = encrypt_token(credentials.token)
    if credentials.refresh_token:
        user.refresh_token = encrypt_token(credentials.refresh_token)
    if credentials.expiry:
        user.token_expiry = credentials.expiry.replace(tzinfo=timezone.utc)
    user.gmail_connected = True
    user.oauth_scopes_granted = json.dumps(list(credentials.scopes or settings.gmail_scopes))


def build_credentials(user: User) -> Credentials:
    scopes = settings.gmail_scopes
    if user.oauth_scopes_granted:
        try:
            granted = json.loads(user.oauth_scopes_granted)
            if isinstance(granted, list):
                scopes = granted
        except Exception:
            pass

    return Credentials(
        token=decrypt_token(user.access_token),
        refresh_token=decrypt_token(user.refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=scopes,
        expiry=_normalize_expiry(user.token_expiry) if user.token_expiry else None,
    )


def refresh_credentials_if_needed(user: User, creds: Credentials) -> Credentials:
    if getattr(creds, "expired", False) and creds.refresh_token:
        creds.refresh(Request())
        store_credentials(user, creds)
    return creds


def get_gmail_service(user: User):
    creds = refresh_credentials_if_needed(user, build_credentials(user))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


async def upsert_user_from_google(
    db: AsyncSession,
    user_info: dict,
    credentials: Credentials,
) -> User:
    google_id = user_info["id"]
    email = user_info["email"]

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.google_id = google_id

    if user:
        user.email = email
        user.name = user_info.get("name")
        user.picture = user_info.get("picture")
    else:
        import uuid

        user = User(
            id=uuid.uuid4(),
            email=email,
            name=user_info.get("name"),
            picture=user_info.get("picture"),
            google_id=google_id,
        )
        db.add(user)

    store_credentials(user, credentials)
    await db.flush()
    log.info("user_authenticated", user_id=str(user.id), email=email)
    return user


def build_frontend_redirect(token: str | None = None, error: str | None = None) -> str:
    if error:
        params = urlencode({"error": error})
    else:
        params = urlencode({"token": token or ""})
    return f"{settings.frontend_url}/auth/callback?{params}"


async def disconnect_gmail(db: AsyncSession, user: User) -> None:
    user.access_token = None
    user.refresh_token = None
    user.token_expiry = None
    user.gmail_connected = False
    user.gmail_history_id = None
    user.initial_sync_complete = False
    user.oauth_scopes_granted = None
    user.sync_status = "idle"
    user.last_sync_at = None
    await db.flush()
    log.info("gmail_disconnected", user_id=str(user.id))
