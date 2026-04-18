"""Persistence for Drive OAuth refresh tokens.

Holds one record per Firebase UID — everything a request-time
handler needs to rebuild a live ``google.oauth2.credentials.Credentials``
and pass it into :class:`GoogleDriveStorageBackend`. Sensitive fields
(refresh token, client secret) are encrypted at the application layer
with AES-GCM before hitting the backing store; the ``Encryptor``
contract is pluggable so tests and dev deployments can swap in a
no-op.

Three implementations ship:

- :class:`TokenStore` — abstract interface (save / load / delete / list).
- :class:`InMemoryTokenStore` — dict-backed; for tests and
  ``OPENBENCH_AUTH_DISABLED`` style local dev.
- :class:`FirestoreTokenStore` — production path; uses the same
  Firestore project Firebase Auth is in. Requires
  ``pip install openbench[firebase]``.

See ``.tmp/RFC-AUTH-LAYER.md`` §6 for the data schema and §10.2 for
the encryption rationale.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "AESGCMEncryptor",
    "DriveToken",
    "Encryptor",
    "FileTokenStore",
    "FirestoreTokenStore",
    "InMemoryTokenStore",
    "NoOpEncryptor",
    "TokenStore",
]


# ---------------------------------------------------------------------------
# DriveToken — single-user record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveToken:
    """OAuth state persisted per Firebase UID.

    Attributes:
        uid: Firebase user id. Primary key.
        refresh_token: Long-lived Google OAuth refresh token. Never log
            this verbatim — always encrypt before persistence.
        client_id: The OAuth 2.0 client id the token was issued for.
        client_secret: The OAuth 2.0 client secret. Encrypted at rest.
        scopes: Scopes the token is good for.
        token_uri: Endpoint to refresh at (usually
            ``https://oauth2.googleapis.com/token``).
        openbench_folder_id: Id of the "OpenBench" folder this user's
            storage is rooted at. Auto-created on first connect.
        connected_email: Human-readable email for UI display.
        created_at: First-connect timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
        revoked_at: Set when the user explicitly disconnects — the
            row may still exist briefly while revocation is
            best-effort dispatched to Google.
    """

    uid: str
    refresh_token: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...] = ()
    token_uri: str = "https://oauth2.googleapis.com/token"
    openbench_folder_id: str | None = None
    connected_email: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: datetime | None = None


# ---------------------------------------------------------------------------
# Encryptor — pluggable application-level at-rest encryption
# ---------------------------------------------------------------------------


class Encryptor(ABC):
    """Plug that wraps AES-GCM (or anything equivalent)."""

    @abstractmethod
    def encrypt(self, plaintext: str) -> str:
        """Return an opaque, URL-safe string that round-trips via ``decrypt``."""

    @abstractmethod
    def decrypt(self, ciphertext: str) -> str:
        """Return the original plaintext produced by ``encrypt``."""


class NoOpEncryptor(Encryptor):
    """Pass-through encryptor — tests and dev only.

    NEVER use in production: refresh tokens are effectively permanent
    credentials and must not sit in any backing store unencrypted.
    """

    def encrypt(self, plaintext: str) -> str:
        return plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


class AESGCMEncryptor(Encryptor):
    """AES-GCM symmetric encryption with a static 32-byte key.

    Wire format:
        ``base64url( nonce(12 bytes) || aesgcm.encrypt(nonce, plaintext, None) )``

    ``AESGCM.encrypt`` already appends the 16-byte authentication tag,
    so decryption does not need to track it separately.

    Lazy-imports :mod:`cryptography` so the rest of the auth package
    loads without that dep. Callers get a helpful install-hint if they
    construct an ``AESGCMEncryptor`` without it present.
    """

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError(
                f"AESGCMEncryptor key must be exactly 32 bytes (AES-256). Got {len(key)} bytes."
            )
        self._key = key
        # Validate the dep exists at construction time so misconfigured
        # deployments fail at startup, not on the first Drive connect.
        self._aesgcm = self._build()

    @classmethod
    def from_env(cls, env_var: str = "DRIVE_TOKEN_ENCRYPTION_KEY") -> AESGCMEncryptor:
        """Load a base64-encoded 32-byte key from an environment variable."""
        raw = (os.environ.get(env_var) or "").strip()
        if not raw:
            raise RuntimeError(
                f"{env_var} must be set to a base64-encoded 32-byte key. "
                f"Generate one with: python -c 'import os,base64; "
                f"print(base64.urlsafe_b64encode(os.urandom(32)).decode())'"
            )
        try:
            key = base64.urlsafe_b64decode(raw)
        except Exception as exc:
            raise RuntimeError(f"{env_var} is not valid base64: {exc}") from exc
        return cls(key)

    def _build(self) -> Any:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise ImportError(
                "AESGCMEncryptor requires the 'cryptography' package. Install via:\n"
                "    pip install openbench[security]\n"
                "or include 'cryptography' in your auth extras."
            ) from exc
        return AESGCM(self._key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.urlsafe_b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        data = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        if len(data) < 13:
            raise ValueError("ciphertext too short to contain nonce + tag")
        nonce, ct = data[:12], data[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode("utf-8")


# ---------------------------------------------------------------------------
# TokenStore — abstract
# ---------------------------------------------------------------------------


class TokenStore(ABC):
    """Persist / retrieve / revoke :class:`DriveToken` records."""

    @abstractmethod
    def save(self, token: DriveToken) -> None:
        """Upsert the token for ``token.uid``."""

    @abstractmethod
    def load(self, uid: str) -> DriveToken | None:
        """Return the token for this uid or ``None``."""

    @abstractmethod
    def delete(self, uid: str) -> None:
        """Remove the token for this uid. No-op if absent."""


# ---------------------------------------------------------------------------
# InMemoryTokenStore — tests + dev
# ---------------------------------------------------------------------------


class InMemoryTokenStore(TokenStore):
    """Dict-backed token store. Data is lost on process restart.

    Applies the configured encryptor so round-trip tests exercise the
    same code path production uses.
    """

    def __init__(self, encryptor: Encryptor | None = None):
        self._encryptor: Encryptor = encryptor or NoOpEncryptor()
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(self, token: DriveToken) -> None:
        with self._lock:
            self._data[token.uid] = _to_record(token, self._encryptor)

    def load(self, uid: str) -> DriveToken | None:
        with self._lock:
            record = self._data.get(uid)
        if record is None:
            return None
        return _from_record(record, self._encryptor)

    def delete(self, uid: str) -> None:
        with self._lock:
            self._data.pop(uid, None)


# ---------------------------------------------------------------------------
# FileTokenStore — localhost / single-node deployments without Firestore
# ---------------------------------------------------------------------------


class FileTokenStore(TokenStore):
    """Filesystem-backed token store — one JSON file per Firebase UID.

    Bridges the gap between :class:`InMemoryTokenStore` (no persistence)
    and :class:`FirestoreTokenStore` (requires Admin SDK + a real
    Firebase project). Fits any single-node deployment whose disk
    survives restart — localhost dev, home-server style hosts, single
    VM deployments.

    Writes are atomic (write-to-tmp + rename) so a mid-write crash
    can't leave a half-serialised record. Filename is URL-safe so
    oddly-shaped uids (phone-auth, federated providers) round-trip
    cleanly.

    Encryption still happens at the :class:`Encryptor` layer — the
    on-disk file contains AES-GCM blobs for refresh_token and
    client_secret, not plaintext.
    """

    def __init__(
        self,
        root_dir: Any,  # str | Path — Path imported lazily in __init__
        *,
        encryptor: Encryptor,
    ):
        if encryptor is None:
            raise ValueError("FileTokenStore requires an Encryptor")
        from pathlib import Path

        self._root = Path(str(root_dir))
        self._encryptor = encryptor
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ TokenStore

    def save(self, token: DriveToken) -> None:
        import json
        from pathlib import Path

        path = self._path_for(token.uid)
        record = _to_record(token, self._encryptor)
        tmp = Path(str(path) + ".tmp")
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(record, fp)
            os.replace(tmp, path)

    def load(self, uid: str) -> DriveToken | None:
        import json

        path = self._path_for(uid)
        with self._lock:
            if not path.exists():
                return None
            try:
                with open(path, encoding="utf-8") as fp:
                    record = json.load(fp)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("FileTokenStore: corrupt record at %s — %s", path, exc)
                return None
        return _from_record(record, self._encryptor)

    def delete(self, uid: str) -> None:
        path = self._path_for(uid)
        with self._lock:
            if path.exists():
                try:
                    path.unlink()
                except OSError as exc:  # pragma: no cover — defensive
                    logger.warning("FileTokenStore: delete failed at %s: %s", path, exc)

    # ---------------------------------------------------------------- internal

    def _path_for(self, uid: str):
        """Return the on-disk path for ``uid``.

        Filename is ``base64url(uid).json`` so arbitrary uid shapes
        (including colons, slashes, phone numbers) can't escape the
        root directory or collide.
        """
        safe = base64.urlsafe_b64encode(uid.encode("utf-8")).rstrip(b"=").decode("ascii")
        return self._root / f"{safe}.json"


# ---------------------------------------------------------------------------
# FirestoreTokenStore — production
# ---------------------------------------------------------------------------


class FirestoreTokenStore(TokenStore):
    """Firestore-backed token store.

    One document per Firebase UID under the ``drive_tokens`` collection
    (configurable). Lazy-imports :mod:`firebase_admin.firestore`.

    Security rules should deny all client access to the collection —
    only this server-side path holds read/write capability via the
    Firebase Admin SDK.
    """

    def __init__(
        self,
        encryptor: Encryptor,
        *,
        firebase_admin_app: Any | None = None,
        collection: str = "drive_tokens",
    ):
        if encryptor is None:
            raise ValueError("FirestoreTokenStore requires an Encryptor")
        self._encryptor = encryptor
        self._collection_name = collection
        self._app = firebase_admin_app
        # Lazy-built firestore client.
        self._client: Any = None
        self._client_lock = threading.Lock()

    def save(self, token: DriveToken) -> None:
        self._get_collection().document(token.uid).set(_to_record(token, self._encryptor))

    def load(self, uid: str) -> DriveToken | None:
        snap = self._get_collection().document(uid).get()
        if not snap.exists:
            return None
        record = snap.to_dict() or {}
        return _from_record(record, self._encryptor)

    def delete(self, uid: str) -> None:
        self._get_collection().document(uid).delete()

    def _get_collection(self) -> Any:
        return self._get_client().collection(self._collection_name)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                self._client = self._build_client()
            return self._client

    def _build_client(self) -> Any:
        try:
            from firebase_admin import firestore
        except ImportError as exc:
            raise ImportError(
                "FirestoreTokenStore requires the 'firebase' extras. Install with:\n"
                "    pip install openbench[firebase]"
            ) from exc
        return firestore.client(app=self._app) if self._app is not None else firestore.client()


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _to_record(token: DriveToken, encryptor: Encryptor) -> dict[str, Any]:
    """Encrypt sensitive fields and shape the token for storage."""
    return {
        "uid": token.uid,
        "refresh_token_enc": encryptor.encrypt(token.refresh_token),
        "client_id": token.client_id,
        "client_secret_enc": encryptor.encrypt(token.client_secret),
        "scopes": list(token.scopes),
        "token_uri": token.token_uri,
        "openbench_folder_id": token.openbench_folder_id,
        "connected_email": token.connected_email,
        "created_at": token.created_at.isoformat(),
        "updated_at": token.updated_at.isoformat(),
        "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
    }


def _from_record(record: dict[str, Any], encryptor: Encryptor) -> DriveToken:
    """Decrypt sensitive fields and rebuild the DriveToken."""
    created_at = _parse_dt(record.get("created_at"))
    updated_at = _parse_dt(record.get("updated_at"))
    revoked_at = _parse_dt(record.get("revoked_at"))
    return DriveToken(
        uid=str(record.get("uid") or ""),
        refresh_token=encryptor.decrypt(str(record.get("refresh_token_enc", ""))),
        client_id=str(record.get("client_id") or ""),
        client_secret=encryptor.decrypt(str(record.get("client_secret_enc", ""))),
        scopes=tuple(record.get("scopes") or ()),
        token_uri=str(record.get("token_uri") or "https://oauth2.googleapis.com/token"),
        openbench_folder_id=record.get("openbench_folder_id"),
        connected_email=record.get("connected_email"),
        created_at=created_at or datetime.now(timezone.utc),
        updated_at=updated_at or datetime.now(timezone.utc),
        revoked_at=revoked_at,
    )


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
