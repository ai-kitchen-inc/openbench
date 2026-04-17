"""Drive OAuth flow internals for lci-mini.

Holds:

- State cookie helpers (``_issue_state_cookie`` / ``_verify_state_cookie``)
  — signed, short-lived, carry the Firebase UID so the callback knows
  whose token to save.
- :func:`get_token_store` singleton — :class:`FirestoreTokenStore` in
  production (real Firebase project), :class:`InMemoryTokenStore` when
  ``OPENBENCH_AUTH_DISABLED=1`` or the encryption key env is missing.
- :func:`ensure_openbench_folder` — find-or-create the per-user
  "OpenBench" folder in their Drive root so subsequent storage
  operations have somewhere to land.

See ``.tmp/RFC-AUTH-LAYER.md`` §5 + §6 for the design rationale.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import secrets
import threading
import time
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from lci_mini.auth.config import AuthConfig, DriveOAuthConfig

if TYPE_CHECKING:
    from openbench.integrations.firebase_auth import TokenStore

logger = logging.getLogger(__name__)

__all__ = [
    "OPENBENCH_FOLDER_NAME",
    "STATE_COOKIE_MAX_AGE",
    "STATE_COOKIE_NAME",
    "ensure_openbench_folder",
    "generate_state",
    "get_token_store",
    "read_state_cookie",
    "sign_state_payload",
]


STATE_COOKIE_NAME = "ob_drive_state"
STATE_COOKIE_MAX_AGE = 600  # seconds — 10 min is plenty for the redirect round-trip
STATE_COOKIE_SALT = "openbench.drive.oauth.state.v1"
OPENBENCH_FOLDER_NAME = "OpenBench"

_FOLDER_MIME = "application/vnd.google-apps.folder"

_token_store_singleton: TokenStore | None = None
_token_store_lock = threading.Lock()


# ---------------------------------------------------------------------------
# State cookie helpers
# ---------------------------------------------------------------------------


def generate_state() -> str:
    """Return a URL-safe CSRF state token."""
    return secrets.token_urlsafe(32)


def sign_state_payload(config: DriveOAuthConfig, payload: dict[str, Any]) -> str:
    """Serialize + HMAC-sign a state payload for storage in the user's cookie.

    Wire format: ``base64url(json(payload_with_ts)).base64url(hmac_sha256)``
    — a tiny home-grown alternative to ``itsdangerous`` so lci-mini
    doesn't grow another runtime dep. Still HMAC-SHA256 + timestamp
    gated so the security posture is equivalent.
    """
    assert config.session_secret is not None
    envelope = {"ts": int(time.time()), "data": payload}
    body = _b64url_encode(json.dumps(envelope, sort_keys=True).encode("utf-8"))
    mac = _b64url_encode(
        hmac.new(
            _hmac_key(config.session_secret),
            body.encode("ascii"),
            sha256,
        ).digest()
    )
    return f"{body}.{mac}"


def read_state_cookie(
    config: DriveOAuthConfig,
    signed_value: str,
    *,
    max_age: int = STATE_COOKIE_MAX_AGE,
) -> dict[str, Any]:
    """Verify + deserialize a signed state cookie.

    Raises:
        ValueError: For malformed / expired / bad-signature payloads.
    """
    assert config.session_secret is not None
    try:
        body, mac = signed_value.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("state cookie malformed") from exc
    expected = _b64url_encode(
        hmac.new(
            _hmac_key(config.session_secret),
            body.encode("ascii"),
            sha256,
        ).digest()
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
    """Namespace the HMAC key so different salts don't share a secret."""
    return (STATE_COOKIE_SALT + ":" + session_secret).encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ---------------------------------------------------------------------------
# Token store singleton
# ---------------------------------------------------------------------------


def get_token_store() -> TokenStore:
    """Return the process-wide :class:`TokenStore`, building it on first call.

    Selection:
    - ``OPENBENCH_AUTH_DISABLED=1`` → :class:`InMemoryTokenStore` with
      :class:`NoOpEncryptor`. Tests / local dev only.
    - Otherwise → :class:`FirestoreTokenStore` backed by an
      :class:`AESGCMEncryptor` keyed from
      ``DRIVE_TOKEN_ENCRYPTION_KEY``.
    """
    global _token_store_singleton
    if _token_store_singleton is not None:
        return _token_store_singleton
    with _token_store_lock:
        if _token_store_singleton is None:
            _token_store_singleton = _build_token_store()
        return _token_store_singleton


def reset_token_store_for_tests() -> None:
    """Drop the singleton so tests can swap backends / encryptors."""
    global _token_store_singleton
    with _token_store_lock:
        _token_store_singleton = None


def _build_token_store() -> TokenStore:
    from openbench.integrations.firebase_auth import (
        AESGCMEncryptor,
        FirestoreTokenStore,
        InMemoryTokenStore,
        NoOpEncryptor,
    )

    cfg = AuthConfig.from_env()
    if cfg.mode == "disabled":
        logger.info("Drive token store: InMemoryTokenStore (auth disabled)")
        return InMemoryTokenStore(encryptor=NoOpEncryptor())

    drive_cfg = DriveOAuthConfig.from_env()
    encryptor = AESGCMEncryptor.from_env(drive_cfg.token_encryption_key_env)
    logger.info("Drive token store: FirestoreTokenStore with AES-GCM encryption")
    return FirestoreTokenStore(encryptor=encryptor)


# ---------------------------------------------------------------------------
# Find-or-create "OpenBench" folder in the authenticated user's Drive
# ---------------------------------------------------------------------------


def ensure_openbench_folder(*, access_token: str) -> str:
    """Return the id of the user's "OpenBench" folder, creating it if absent.

    Uses the freshly-issued access token from the OAuth callback to
    talk to Drive. No refresh-token is needed because this call
    happens inside the same user interaction that issued the access
    token — it is still well within the 1-hour expiry window.
    """
    service = _build_drive_service_with_token(access_token)
    query = (
        f"name = '{OPENBENCH_FOLDER_NAME}' "
        f"and mimeType = '{_FOLDER_MIME}' "
        "and 'root' in parents "
        "and trashed = false"
    )
    resp = (
        service.files()
        .list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
            spaces="drive",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = resp.get("files") or []
    if files:
        return str(files[0]["id"])
    created = (
        service.files()
        .create(
            body={
                "name": OPENBENCH_FOLDER_NAME,
                "parents": ["root"],
                "mimeType": _FOLDER_MIME,
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return str(created["id"])


def _build_drive_service_with_token(access_token: str) -> Any:
    """Build a Drive v3 service authenticated with a bare access token.

    Unlike :class:`GoogleDriveStorageBackend`'s service, this one uses
    a non-refreshable ``google.oauth2.credentials.Credentials`` — we
    only need a single Drive call (find-or-create folder) so refresh
    is irrelevant here.
    """
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "Drive folder auto-create requires the 'gdrive' extras:\n"
            "    pip install openbench[gdrive]"
        ) from exc
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds, cache_discovery=False)
