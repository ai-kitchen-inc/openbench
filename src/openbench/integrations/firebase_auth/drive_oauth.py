"""Server-initiated Google Drive OAuth 2.0 flow helpers.

Firebase Auth's Google provider only exposes a short-lived access
token, never a refresh token. To keep Drive access durable without
forcing hourly re-sign-ins, we run a **second, explicit** OAuth flow
at the moment the user first opts into Drive-backed storage. This
module is the glue for that flow:

- :func:`build_authorize_url` — construct the URL the user is
  redirected to for consent (``access_type=offline`` +
  ``prompt=consent`` so Google guarantees a refresh token).
- :func:`exchange_code` — trade the authorization code returned to
  ``/auth/drive/callback`` for a fresh access token + refresh token.
- :func:`refresh_access_token` — swap the long-lived refresh token
  for a short-lived access token at request time.
- :func:`revoke_refresh_token` — best-effort revoke when the user
  disconnects Drive.
- :func:`build_credentials` — wrap the stored tokens as a
  ``google.oauth2.credentials.Credentials`` object suitable for
  passing into :class:`GoogleDriveStorageBackend(credentials=...)`.

All HTTP calls use :mod:`urllib` from stdlib so the core SDK does not
grow a new runtime dependency. Google's OAuth 2.0 endpoints are
stable enough that a hand-rolled client is fine.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "ClientSecrets",
    "OAuthError",
    "TokenResponse",
    "build_authorize_url",
    "build_credentials",
    "exchange_code",
    "load_client_secrets",
    "refresh_access_token",
    "revoke_refresh_token",
]

# Google's OAuth 2.0 endpoints.
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# Scope the docs call out — callers pass a full list; this is the
# bare minimum to let GoogleDriveStorageBackend create + read files
# the app owns.
DEFAULT_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/drive.file",)

_DEFAULT_TIMEOUT = 10.0  # seconds


class OAuthError(Exception):
    """Any failure from Google's OAuth 2.0 endpoints."""


@dataclass(frozen=True)
class ClientSecrets:
    """Normalized client-secrets parsed from a downloaded Google JSON file."""

    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...] = ()


@dataclass(frozen=True)
class TokenResponse:
    """Normalized response from the OAuth token endpoint.

    Matches Google's documented shape minus the bits we don't use.
    """

    access_token: str
    expires_at: float  # epoch seconds when ``access_token`` expires
    scope: str
    token_type: str = "Bearer"
    # refresh_token is only returned on the initial authorization code
    # exchange; subsequent refresh calls return only the access token.
    refresh_token: str | None = None


# ---------------------------------------------------------------------------
# Authorize URL
# ---------------------------------------------------------------------------


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str] | tuple[str, ...],
    state: str,
    login_hint: str | None = None,
) -> str:
    """Return the URL a browser should be redirected to for consent.

    Args:
        client_id: OAuth 2.0 Web Client ID from Google Cloud Console.
        redirect_uri: Must exactly match an authorized redirect URI
            on the client. The callback endpoint receives the code.
        scopes: Google API scopes to request (e.g.
            ``https://www.googleapis.com/auth/drive.file``).
        state: Opaque CSRF token; the callback MUST verify this
            matches what the server issued.
        login_hint: Optional user email — pre-fills the Google account
            chooser so the user does not have to type or pick an
            account when they already signed in via Firebase.

    Returns:
        Fully-formed authorize URL.
    """
    if not client_id:
        raise ValueError("client_id must be a non-empty string")
    if not redirect_uri:
        raise ValueError("redirect_uri must be a non-empty string")
    if not scopes:
        raise ValueError("scopes must contain at least one scope")
    if not state:
        raise ValueError("state must be a non-empty string")

    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        # ``offline`` tells Google to return a refresh token.
        "access_type": "offline",
        # ``consent`` forces the consent screen so a refresh token is
        # issued even if the user previously granted this scope — edge
        # cases otherwise skip the refresh-token issuance.
        "prompt": "consent",
        "state": state,
        # ``include_granted_scopes=true`` lets incremental auth flows
        # augment existing grants without re-asking for everything.
        "include_granted_scopes": "true",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange / refresh / revoke
# ---------------------------------------------------------------------------


def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> TokenResponse:
    """Trade an authorization code for access + refresh tokens.

    Raises:
        OAuthError: If Google returns a non-2xx response.
    """
    if not code:
        raise ValueError("code must be a non-empty string")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    return _post_token(data, timeout=timeout)


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> TokenResponse:
    """Exchange a refresh token for a fresh access token.

    The returned :class:`TokenResponse` has ``refresh_token = None``
    because Google only issues refresh tokens on the initial
    authorization-code exchange. Callers keep the original refresh
    token until it is explicitly revoked by Google (``invalid_grant``
    on refresh).
    """
    if not refresh_token:
        raise ValueError("refresh_token must be a non-empty string")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    return _post_token(data, timeout=timeout)


def revoke_refresh_token(
    refresh_token: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> bool:
    """Revoke a refresh token at Google's endpoint.

    Returns True on success, False on failure (best-effort — callers
    should still delete their local copy of the token either way).
    """
    if not refresh_token:
        return False
    body = urllib.parse.urlencode({"token": refresh_token}).encode("utf-8")
    req = urllib.request.Request(
        _REVOKE_ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        logger.warning("Revoke failed (HTTP %s): %s", exc.code, exc.reason)
        return False
    except urllib.error.URLError as exc:
        logger.warning("Revoke failed (network): %s", exc.reason)
        return False


def _post_token(
    payload: dict[str, str],
    *,
    timeout: float,
) -> TokenResponse:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        _TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = _safe_error_body(exc)
        raise OAuthError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OAuthError(f"Network error: {exc.reason}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OAuthError(f"Malformed JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise OAuthError("Token response was not a JSON object")

    if "access_token" not in data:
        raise OAuthError(f"Token response missing access_token: {data}")

    expires_in = int(data.get("expires_in", 3600))
    now = time.time()
    return TokenResponse(
        access_token=str(data["access_token"]),
        refresh_token=data.get("refresh_token"),
        expires_at=now + expires_in,
        scope=str(data.get("scope", "")),
        token_type=str(data.get("token_type", "Bearer")),
    )


def _safe_error_body(exc: urllib.error.HTTPError) -> str:
    """Best-effort extract of the response body on an HTTP error."""
    try:
        body = exc.read().decode("utf-8", errors="replace")
        return body[:500]
    except Exception:  # pragma: no cover — defensive
        return exc.reason or ""


# ---------------------------------------------------------------------------
# Client secrets file loader
# ---------------------------------------------------------------------------


def load_client_secrets(path: str | Path) -> ClientSecrets:
    """Parse a Google-downloaded OAuth 2.0 Web client JSON file.

    The expected top-level shape is ``{"web": {"client_id": ...,
    "client_secret": ..., "redirect_uris": [...]}}``. Raises
    :class:`ValueError` for missing required fields so misconfiguration
    fails fast at startup rather than at first request.
    """
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    root = data.get("web") or data.get("installed")
    if not isinstance(root, dict):
        raise ValueError(f"client_secrets file {path!r} has neither 'web' nor 'installed' key")
    client_id = root.get("client_id")
    client_secret = root.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError(f"client_secrets file {path!r} missing client_id or client_secret")
    redirect_uris = tuple(root.get("redirect_uris") or ())
    return ClientSecrets(
        client_id=str(client_id),
        client_secret=str(client_secret),
        redirect_uris=redirect_uris,
    )


# ---------------------------------------------------------------------------
# Build google.oauth2.credentials.Credentials for GoogleDriveStorageBackend
# ---------------------------------------------------------------------------


def build_credentials(
    *,
    access_token: str | None = None,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | tuple[str, ...] | None = None,
    token_uri: str = _TOKEN_ENDPOINT,
) -> Any:
    """Wrap stored OAuth tokens as a ``google.oauth2.credentials.Credentials``.

    The resulting object auto-refreshes when Drive API calls detect an
    expired or missing access token — this is how the ``credentials=``
    parameter on :class:`GoogleDriveStorageBackend` stays alive across
    requests even when only the refresh token is persisted.

    Pass ``access_token=None`` (the default) or an empty string to force
    a fresh refresh on first use; google-auth treats both as "no token"
    and swaps in a new one via the ``refresh_token`` + ``token_uri``.

    Lazy-imports ``google-auth`` so this module loads without the
    ``[gdrive]`` extras installed.
    """
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise ImportError(
            "build_credentials requires the 'gdrive' extras. Install with:\n"
            "    pip install openbench[gdrive]"
        ) from exc
    # Empty string "" still looks like a valid token to google-auth and
    # suppresses the refresh path — normalise to None so the first API
    # call triggers refresh_access_token() via the refresh_token.
    token = access_token if access_token else None
    return Credentials(
        token=token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(scopes) if scopes else None,
    )
