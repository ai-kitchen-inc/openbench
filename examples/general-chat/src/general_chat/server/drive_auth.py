"""Per-user Google Drive OAuth for general-chat.

Adapted from lci-mini's ``build_drive_router`` (see
``examples/lci-mini/src/lci_mini/auth/endpoints.py``) on top of the SDK
helpers in :mod:`openbench.integrations.firebase_auth`:

- Identity is the general-chat **owner** (lowercased email, or
  ``local`` when auth is disabled) via :func:`current_owner` — not a
  Firebase UID.
- Scope defaults to ``drive.readonly``: the point is reading the
  user's existing files as chat sources, which the SDK default
  ``drive.file`` scope cannot do.
- No "OpenBench" folder bootstrap — that would require write scope.
- Refresh tokens persist in a :class:`FileTokenStore` under
  ``{storage_root}/drive_tokens/``, AES-GCM encrypted (the encryption
  key is mandatory whenever OAuth is configured).

Endpoints (mounted under ``/auth/drive``):

- ``POST /connect``    — authorize URL + signed state cookie
- ``GET  /callback``   — code exchange + token persist (cookie identity,
  no bearer: browsers drop Authorization headers on Google's redirect)
- ``POST /disconnect`` — best-effort revoke + delete
- ``GET  /status``     — ``{configured, connected, email}``
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from general_chat.server.auth import current_owner

logger = logging.getLogger(__name__)

# Firebase Hosting's CDN forwards only the "__session" cookie to backend
# rewrites; path-scoped to /auth/drive so it collides with nothing else.
STATE_COOKIE_NAME = "__session"
STATE_COOKIE_MAX_AGE = 600  # seconds — plenty for the consent round-trip
_STATE_COOKIE_SALT = "general-chat.drive.oauth.state.v1"

DEFAULT_DRIVE_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive.readonly",
)

MSG_NOT_CONFIGURED = (
    "Integrasi Google Drive belum dikonfigurasi di server. "
    "Set GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS untuk mengaktifkannya."
)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveOAuthSettings:
    """Env-derived Drive OAuth configuration.

    The feature is enabled by the presence of
    ``GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS``; the companion vars are
    then required and missing ones fail fast at startup.
    """

    client_secrets_path: str | None
    redirect_url: str | None
    session_secret: str | None
    scopes: tuple[str, ...]
    redirect_home: str

    @property
    def enabled(self) -> bool:
        return bool(self.client_secrets_path)

    @classmethod
    def from_env(cls) -> DriveOAuthSettings:
        secrets_path = (
            os.getenv("GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS") or ""
        ).strip() or None
        redirect_url = (
            os.getenv("GENERAL_CHAT_DRIVE_OAUTH_REDIRECT_URL") or ""
        ).strip() or None
        session_secret = (os.getenv("GENERAL_CHAT_SESSION_SECRET") or "").strip() or None
        raw_scopes = (os.getenv("GENERAL_CHAT_DRIVE_OAUTH_SCOPES") or "").strip()
        scopes = (
            tuple(s.strip() for s in raw_scopes.split(",") if s.strip())
            if raw_scopes
            else DEFAULT_DRIVE_SCOPES
        )
        redirect_home = (
            os.getenv("GENERAL_CHAT_DRIVE_OAUTH_REDIRECT_HOME") or ""
        ).strip() or "/"

        if secrets_path:
            missing: list[str] = []
            if not redirect_url:
                missing.append("GENERAL_CHAT_DRIVE_OAUTH_REDIRECT_URL")
            if not session_secret:
                missing.append(
                    "GENERAL_CHAT_SESSION_SECRET "
                    "(generate: python -c \"import secrets;"
                    'print(secrets.token_urlsafe(32))")'
                )
            if not (os.getenv("GENERAL_CHAT_DRIVE_TOKEN_ENCRYPTION_KEY") or "").strip():
                missing.append(
                    "GENERAL_CHAT_DRIVE_TOKEN_ENCRYPTION_KEY "
                    "(generate: python -c \"import os,base64;"
                    'print(base64.urlsafe_b64encode(os.urandom(32)).decode())")'
                )
            if missing:
                raise RuntimeError(
                    "GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS is set but Drive "
                    "OAuth is incompletely configured. Missing: "
                    + "; ".join(missing)
                )
            if not Path(secrets_path).is_file():
                raise RuntimeError(
                    "GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS points to a "
                    f"missing file: {secrets_path}"
                )
        return cls(
            client_secrets_path=secrets_path,
            redirect_url=redirect_url,
            session_secret=session_secret,
            scopes=scopes,
            redirect_home=redirect_home,
        )


# ---------------------------------------------------------------------------
# Signed state cookie (HMAC-SHA256 + timestamp; format per lci-mini)
# ---------------------------------------------------------------------------


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def sign_state_payload(session_secret: str, payload: dict[str, Any]) -> str:
    envelope = {"ts": int(time.time()), "data": payload}
    body = _b64url_encode(json.dumps(envelope, sort_keys=True).encode("utf-8"))
    mac = _b64url_encode(
        hmac.new(_hmac_key(session_secret), body.encode("ascii"), sha256).digest()
    )
    return f"{body}.{mac}"


def read_state_cookie(
    session_secret: str,
    signed_value: str,
    *,
    max_age: int = STATE_COOKIE_MAX_AGE,
) -> dict[str, Any]:
    """Verify + deserialize a signed state cookie; ValueError on any defect."""
    try:
        body, mac = signed_value.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("state cookie malformed") from exc
    expected = _b64url_encode(
        hmac.new(_hmac_key(session_secret), body.encode("ascii"), sha256).digest()
    )
    if not hmac.compare_digest(mac, expected):
        raise ValueError("state cookie signature invalid")
    try:
        envelope = json.loads(_b64url_decode(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("state cookie body malformed") from exc
    ts = envelope.get("ts")
    if not isinstance(ts, int) or time.time() - ts > max_age:
        raise ValueError("state cookie expired")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ValueError("state cookie payload malformed")
    return data


def _hmac_key(session_secret: str) -> bytes:
    return (_STATE_COOKIE_SALT + ":" + session_secret).encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ---------------------------------------------------------------------------
# Rate limiting (sliding window, per owner)
# ---------------------------------------------------------------------------


class RateLimited(Exception):
    def __init__(self, retry_after_s: float):
        super().__init__(f"rate limited; retry after {retry_after_s:.0f}s")
        self.retry_after_s = retry_after_s


class _SlidingWindowLimiter:
    def __init__(self, max_events: int = 10, window_s: float = 3600.0):
        self._max = max_events
        self._window = window_s
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < self._window]
            if len(events) >= self._max:
                raise RateLimited(self._window - (now - events[0]))
            events.append(now)
            self._events[key] = events


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class DriveOAuthManager:
    """Owns Drive OAuth settings, the token store, and the API router."""

    def __init__(self, storage_root: str):
        self.settings = DriveOAuthSettings.from_env()
        self._storage_root = storage_root
        self._store: Any | None = None
        self._store_lock = threading.Lock()
        self._limiter = _SlidingWindowLimiter()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def _token_store(self) -> Any:
        if self._store is not None:
            return self._store
        with self._store_lock:
            if self._store is None:
                from openbench.integrations.firebase_auth import (
                    AESGCMEncryptor,
                    FileTokenStore,
                )

                self._store = FileTokenStore(
                    root_dir=Path(self._storage_root) / "drive_tokens",
                    encryptor=AESGCMEncryptor.from_env(
                        "GENERAL_CHAT_DRIVE_TOKEN_ENCRYPTION_KEY"
                    ),
                )
            return self._store

    def credentials_for(self, owner: str) -> Any | None:
        """Return refreshable Google credentials for ``owner``, or None."""
        if not self.enabled:
            return None
        try:
            token = self._token_store().load(owner)
        except Exception:  # pragma: no cover — defensive: corrupt store entry
            logger.exception("Drive token load failed for owner=%s", owner)
            return None
        if token is None:
            return None
        from openbench.integrations.firebase_auth import build_credentials

        return build_credentials(
            refresh_token=token.refresh_token,
            client_id=token.client_id,
            client_secret=token.client_secret,
            scopes=token.scopes or self.settings.scopes,
        )

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=MSG_NOT_CONFIGURED,
            )

    @staticmethod
    def _fetch_account_email(access_token: str) -> str | None:
        """Best-effort Google-account email for UI display (stdlib only)."""
        import urllib.request

        req = urllib.request.Request(
            "https://www.googleapis.com/drive/v3/about?fields=user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            email = (data.get("user") or {}).get("emailAddress")
            return str(email) if email else None
        except Exception as exc:
            logger.warning("Could not resolve Drive account email: %s", exc)
            return None

    def build_router(self) -> APIRouter:
        router = APIRouter(prefix="/auth/drive", tags=["auth"])

        @router.post("/connect")
        async def connect(request: Request) -> JSONResponse:
            self._require_enabled()
            owner = current_owner(request)
            try:
                self._limiter.check(f"connect:{owner}")
            except RateLimited as exc:
                retry = int(exc.retry_after_s) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        "Terlalu banyak percobaan menghubungkan Drive. "
                        f"Coba lagi dalam {retry} detik."
                    ),
                    headers={"Retry-After": str(retry)},
                ) from exc

            from openbench.integrations.firebase_auth import (
                build_authorize_url,
                load_client_secrets,
            )

            client = load_client_secrets(self.settings.client_secrets_path)
            state = generate_state()
            url = build_authorize_url(
                client_id=client.client_id,
                redirect_uri=self.settings.redirect_url,
                scopes=list(self.settings.scopes),
                state=state,
                login_hint=owner if "@" in owner else None,
            )
            signed = sign_state_payload(
                self.settings.session_secret or "",
                {"owner": owner, "state": state},
            )
            response = JSONResponse({"authorizeUrl": url})
            response.set_cookie(
                key=STATE_COOKIE_NAME,
                value=signed,
                max_age=STATE_COOKIE_MAX_AGE,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                path="/auth/drive",
            )
            return response

        @router.get("/callback")
        async def callback(
            request: Request,
            code: str | None = None,
            state: str | None = None,
            error: str | None = None,
            cookie_value: str | None = Cookie(None, alias=STATE_COOKIE_NAME),
        ):
            self._require_enabled()
            if error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Google OAuth error: {error}",
                )
            if not code or not state:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing required code or state parameter",
                )
            if not cookie_value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing state cookie",
                )
            try:
                payload = read_state_cookie(
                    self.settings.session_secret or "", cookie_value
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid state cookie: {exc}",
                ) from exc
            if payload.get("state") != state:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CSRF state mismatch",
                )
            owner = str(payload.get("owner") or "")
            if not owner:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="State cookie missing owner",
                )

            from openbench.integrations.firebase_auth import (
                DriveToken,
                exchange_code,
                load_client_secrets,
            )

            try:
                client = load_client_secrets(self.settings.client_secrets_path)
                token_response = exchange_code(
                    client_id=client.client_id,
                    client_secret=client.client_secret,
                    redirect_uri=self.settings.redirect_url or "",
                    code=code,
                )
            except Exception as exc:
                logger.exception("Drive token exchange failed for owner=%s", owner)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Token exchange with Google failed: {exc!s}",
                ) from exc
            if not token_response.refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Google returned no refresh_token. Ensure the "
                        "authorize URL includes access_type=offline and "
                        "prompt=consent (this should be automatic)."
                    ),
                )

            connected_email = self._fetch_account_email(token_response.access_token)
            now = datetime.now(timezone.utc)
            try:
                self._token_store().save(
                    DriveToken(
                        uid=owner,
                        refresh_token=token_response.refresh_token,
                        client_id=client.client_id,
                        client_secret=client.client_secret,
                        scopes=tuple(self.settings.scopes),
                        connected_email=connected_email,
                        created_at=now,
                        updated_at=now,
                    )
                )
            except Exception as exc:
                logger.exception("Failed to persist Drive token for owner=%s", owner)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Could not save Drive token: {exc!s}",
                ) from exc

            home = self.settings.redirect_home
            separator = "&" if "?" in home else "?"
            response = RedirectResponse(
                url=f"{home}{separator}drive=connected", status_code=302
            )
            response.delete_cookie(STATE_COOKIE_NAME, path="/auth/drive")
            return response

        @router.post("/disconnect")
        async def disconnect(request: Request) -> dict:
            self._require_enabled()
            owner = current_owner(request)
            from openbench.integrations.firebase_auth import revoke_refresh_token

            store = self._token_store()
            existing = store.load(owner)
            if existing is None:
                return {"disconnected": False, "reason": "not connected"}
            try:
                revoke_refresh_token(existing.refresh_token)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "Drive refresh-token revoke failed for owner=%s: %s", owner, exc
                )
            store.delete(owner)
            return {"disconnected": True}

        @router.get("/status")
        async def status_endpoint(request: Request) -> dict:
            if not self.enabled:
                return {"configured": False, "connected": False, "email": None}
            owner = current_owner(request)
            try:
                token = self._token_store().load(owner)
            except Exception:  # pragma: no cover — defensive
                logger.exception("Drive token load failed for owner=%s", owner)
                token = None
            return {
                "configured": True,
                "connected": token is not None,
                "email": token.connected_email if token is not None else None,
            }

        return router
