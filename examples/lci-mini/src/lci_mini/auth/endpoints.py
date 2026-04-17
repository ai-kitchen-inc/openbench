"""FastAPI routes for the Drive OAuth flow.

Exports :func:`build_drive_router` — call it from ``create_app()`` and
include the resulting router. Four endpoints ship:

- ``POST /auth/drive/connect``    — issue authorize URL + state cookie
- ``GET  /auth/drive/callback``   — exchange code, persist token, redirect home
- ``POST /auth/drive/disconnect`` — revoke + delete token
- ``GET  /auth/drive/status``     — report whether the user is connected

The three authenticated endpoints depend on
:func:`verify_firebase_token`; the callback endpoint deliberately does
not, because browsers don't carry custom Authorization headers during
a 302 redirect back from Google's OAuth consent screen. Identity in
that one spot comes from the signed state cookie.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from lci_mini.auth.config import DriveOAuthConfig
from lci_mini.auth.dependencies import verify_firebase_token
from lci_mini.auth.drive import (
    STATE_COOKIE_MAX_AGE,
    STATE_COOKIE_NAME,
    ensure_openbench_folder,
    generate_state,
    get_token_store,
    read_state_cookie,
    sign_state_payload,
)

if TYPE_CHECKING:
    from openbench.integrations.firebase_auth import FirebaseUser

logger = logging.getLogger(__name__)


def build_drive_router(redirect_home: str = "/") -> APIRouter:
    """Return an ``APIRouter`` mounted under ``/auth/drive``.

    Args:
        redirect_home: Where to bounce the user after successful
            callback. Defaults to the app root.
    """
    router = APIRouter(prefix="/auth/drive", tags=["auth"])

    def _require_drive_cfg() -> DriveOAuthConfig:
        cfg = DriveOAuthConfig.from_env()
        if not cfg.enabled:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=(
                    "Drive OAuth is not configured. Set "
                    "GOOGLE_OAUTH_CLIENT_SECRETS + DRIVE_OAUTH_REDIRECT_URL "
                    "+ SESSION_SECRET."
                ),
            )
        return cfg

    @router.post("/connect")
    async def connect(
        request: Request,
        user: FirebaseUser = Depends(verify_firebase_token),
    ) -> dict:
        """Return the authorize URL and set a signed state cookie.

        Frontend POSTs here with the user's Firebase ID token, reads
        ``authorizeUrl`` from the response, and navigates the browser
        to that URL. The cookie piggybacks the response so that
        Google's subsequent callback round-trip can verify it.
        """
        from openbench.integrations.firebase_auth import (
            build_authorize_url,
            load_client_secrets,
        )

        cfg = _require_drive_cfg()
        assert cfg.client_secrets_path is not None
        assert cfg.redirect_url is not None

        secrets = load_client_secrets(cfg.client_secrets_path)
        state = generate_state()
        url = build_authorize_url(
            client_id=secrets.client_id,
            redirect_uri=cfg.redirect_url,
            scopes=list(cfg.scopes),
            state=state,
            login_hint=user.email,
        )
        signed = sign_state_payload(cfg, {"uid": user.uid, "state": state})
        # Register the cookie on the response via FastAPI's dependency-side
        # trick: attach to a temporary dict the Response object will merge.
        response = _json_response({"authorizeUrl": url})
        # Determine whether we're running under TLS so Secure cookies are
        # set correctly. Tests use http:// so Secure would block the cookie.
        secure = request.url.scheme == "https"
        response.set_cookie(
            key=STATE_COOKIE_NAME,
            value=signed,
            max_age=STATE_COOKIE_MAX_AGE,
            httponly=True,
            secure=secure,
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
        """Exchange ``code`` for tokens after the user granted consent.

        Verifies the signed state cookie, recovers the Firebase UID,
        calls the token endpoint, ensures the "OpenBench" Drive folder
        exists, and persists the token to the configured store. Then
        redirects the browser back to ``redirect_home``.
        """
        from openbench.integrations.firebase_auth import (
            DriveToken,
            exchange_code,
            load_client_secrets,
        )

        cfg = _require_drive_cfg()
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
            payload = read_state_cookie(cfg, cookie_value)
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
        uid = str(payload.get("uid") or "")
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="State cookie missing uid",
            )

        secrets = load_client_secrets(cfg.client_secrets_path)  # type: ignore[arg-type]
        assert cfg.redirect_url is not None
        tok = exchange_code(
            client_id=secrets.client_id,
            client_secret=secrets.client_secret,
            redirect_uri=cfg.redirect_url,
            code=code,
        )
        if not tok.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Google returned no refresh_token. Ensure the "
                    "authorize URL includes access_type=offline and "
                    "prompt=consent (this should be automatic)."
                ),
            )

        folder_id = ensure_openbench_folder(access_token=tok.access_token)

        store = get_token_store()
        now = datetime.now(timezone.utc)
        store.save(
            DriveToken(
                uid=uid,
                refresh_token=tok.refresh_token,
                client_id=secrets.client_id,
                client_secret=secrets.client_secret,
                scopes=tuple(cfg.scopes),
                token_uri="https://oauth2.googleapis.com/token",
                openbench_folder_id=folder_id,
                created_at=now,
                updated_at=now,
            )
        )
        # Bounce back to the SPA. Clear the state cookie on the way out.
        response = RedirectResponse(url=redirect_home, status_code=302)
        response.delete_cookie(STATE_COOKIE_NAME, path="/auth/drive")
        return response

    @router.post("/disconnect")
    async def disconnect(
        user: FirebaseUser = Depends(verify_firebase_token),
    ) -> dict:
        """Revoke the refresh token at Google and delete our copy."""
        from openbench.integrations.firebase_auth import revoke_refresh_token

        _require_drive_cfg()
        store = get_token_store()
        existing = store.load(user.uid)
        if existing is None:
            return {"disconnected": False, "reason": "not connected"}
        # Best-effort revoke — even if Google fails, we still drop
        # our local copy so the app stops using it.
        try:
            revoke_refresh_token(existing.refresh_token)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Refresh-token revoke failed for uid=%s: %s", user.uid, exc)
        store.delete(user.uid)
        return {"disconnected": True}

    @router.get("/status")
    async def status_endpoint(
        user: FirebaseUser = Depends(verify_firebase_token),
    ) -> dict:
        """Report whether the user has connected Drive."""
        # Status is allowed even when drive OAuth isn't configured — the
        # frontend uses the 'connected: false' signal to render the
        # 'Connect Drive' prompt.
        store = get_token_store()
        existing = store.load(user.uid)
        if existing is None:
            return {"connected": False}
        return {
            "connected": True,
            "email": existing.connected_email,
            "folderId": existing.openbench_folder_id,
            "scopes": list(existing.scopes),
        }

    return router


# ---------------------------------------------------------------------------
# Small helper — FastAPI's JSONResponse with cookies requires a concrete
# Response object; wrap it once.
# ---------------------------------------------------------------------------


def _json_response(data: dict):
    from fastapi.responses import JSONResponse

    return JSONResponse(data)
