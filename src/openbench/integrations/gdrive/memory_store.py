"""Agent memory persistence backed by a Google Drive folder.

Each session is stored as a single ``<session_id>.json`` blob inside a
``memory/`` subfolder of the user's OpenBench folder. Layout::

    <openbench-folder>/
    └── memory/
        ├── session-abc123.json
        └── session-xyz789.json

Each blob is a JSON document::

    {
      "session_id": "...",
      "version": 1,
      "updated_at": "<ISO 8601>",
      "messages": [
        {"role": "...", "content": "...", "tool_calls": [...], ...},
        ...
      ]
    }

**v1.5 scope (RFC-UNIFIED-MEMORY-STORAGE Phase 2)**: correctness +
TTL-based read cache. Implements full :class:`MemoryStore` ABC,
passes :class:`MemoryStoreContract`, and skips redundant Drive reads
inside the cache freshness window (default 30s, see
:class:`_EtagCache`). Deferred to follow-up commits:

- ETag/version validation on the cached entry (the cache currently
  trusts the TTL only; future iteration can add a HEAD against
  ``files.get(fields="version")`` so cross-device updates invalidate
  faster than the TTL).
- Optimistic concurrency via ``If-Match`` (RFC §6.3) — concurrent
  writes are last-write-wins for now. Tolerable in v1: per-user
  concurrency on the same session_id is rare (one user, one device
  at a time in the typical flow).
- Pending-sync fallback to local SQLite on Drive failure (RFC §8) —
  v1 surfaces Drive errors directly via raised exceptions, letting
  the caller (e.g. PersistentMemory.turn() rollback) handle them.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from openbench.integrations.gdrive._etag_cache import _EtagCache
from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.memory import MemoryStore

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["GoogleDriveMemoryStore"]

# Drive scope must allow read+write+delete. The session/file/scratchpad
# stores already use the same scope, so no new consent is required.
_DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive",)

_FILE_EXT = ".json"
_MIME_TYPE = "application/json"
_FOLDER_MIME = "application/vnd.google-apps.folder"

_BLOB_VERSION = 1


def _missing_dep_message() -> str:
    return (
        "GoogleDriveMemoryStore requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]\n"
        "which pulls google-api-python-client and google-auth."
    )


def _serialize_message(msg: Message) -> dict[str, Any]:
    """Serialize a :class:`Message` to a JSON-safe dict.

    Mirrors the SQLite store's persisted columns: role / content /
    name / tool_call_id / tool_calls. The transient ``raw_content``
    field is intentionally dropped — it's the LLM provider's raw
    response and not part of the stable memory wire format.
    """
    out: dict[str, Any] = {"role": msg.role.value, "content": msg.content}
    if msg.name is not None:
        out["name"] = msg.name
    if msg.tool_call_id is not None:
        out["tool_call_id"] = msg.tool_call_id
    if msg.tool_calls is not None:
        out["tool_calls"] = msg.tool_calls
    return out


def _deserialize_message(data: dict[str, Any]) -> Message:
    """Reverse of :func:`_serialize_message`."""
    return Message(
        role=MessageRole(data["role"]),
        content=data.get("content", ""),
        name=data.get("name"),
        tool_call_id=data.get("tool_call_id"),
        tool_calls=data.get("tool_calls"),
    )


def _build_blob(session_id: str, messages: list[Message]) -> str:
    """JSON-encode a session's full message history."""
    payload = {
        "session_id": session_id,
        "version": _BLOB_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "messages": [_serialize_message(m) for m in messages],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_blob(text: str) -> list[Message]:
    """Decode a JSON blob into a list of Messages.

    Tolerates corrupted / unparseable blobs by returning ``[]`` and
    logging — this matches :class:`GoogleDriveSessionStore`'s
    "skip don't crash" stance for externally-edited files.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Skipping corrupt memory blob: %s", exc)
        return []
    raw = payload.get("messages") or []
    out: list[Message] = []
    for entry in raw:
        try:
            out.append(_deserialize_message(entry))
        except (ValueError, KeyError) as exc:
            logger.warning("Skipping unparseable message in blob: %s", exc)
    return out


class GoogleDriveMemoryStore(MemoryStore):
    """Drive-backed :class:`MemoryStore`.

    Constructor authentication (one must be provided):

    - ``service_account_file``: path to a service-account JSON key.
    - ``credentials``: a pre-built credentials object.

    The service account (or user) must have Editor access on the
    folder. The store creates a ``memory/`` subfolder lazily on first
    write.

    Example::

        store = GoogleDriveMemoryStore(
            folder_id="abc123",
            credentials=user_oauth_credentials,
        )
        store.save("session-1", [Message(role=MessageRole.USER, content="hi")])
        loaded = store.load("session-1")
    """

    def __init__(
        self,
        folder_id: str,
        *,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
        subfolder_name: str = "memory",
        cache_ttl_seconds: float = 30.0,
        cache_max_sessions: int = 100,
        enable_cache: bool = True,
    ):
        if not folder_id:
            raise ValueError("folder_id must be a non-empty string")
        if service_account_file is None and credentials is None:
            raise ValueError("Either service_account_file= or credentials= must be provided.")
        if not subfolder_name:
            raise ValueError("subfolder_name must be a non-empty string")

        self.folder_id = folder_id
        self.subfolder_name = subfolder_name
        self._service_account_file = (
            str(service_account_file) if service_account_file is not None else None
        )
        self._explicit_credentials = credentials
        self._service: Any = None
        self._service_lock = threading.Lock()
        # Cached subfolder id, resolved on first use. None until then.
        self._subfolder_id: str | None = None
        self._subfolder_lock = threading.Lock()
        # Read-side cache. Enabled by default; pass ``enable_cache=False``
        # for tests / callers that need to assert every load round-trips
        # to Drive.
        self._cache: _EtagCache | None = (
            _EtagCache(max_sessions=cache_max_sessions, ttl_seconds=cache_ttl_seconds)
            if enable_cache
            else None
        )

    # ------------------------------------------------------------------ MemoryStore

    def save(self, session_id: str, messages: list[Message]) -> None:
        """Append ``messages`` to ``session_id``'s history.

        Blob-store semantics: read existing, append, write back. Empty
        ``messages`` is a no-op (matches the contract). Updates the
        read cache with the merged history so the next ``load`` is a
        cache hit instead of a Drive round-trip.
        """
        if not messages:
            return
        existing = self.load(session_id)
        merged = existing + list(messages)
        self._write_session(session_id, merged)
        if self._cache is not None:
            self._cache.put(session_id, merged)

    def load(self, session_id: str) -> list[Message]:
        """Return the full message history for ``session_id``.

        Returns ``[]`` for unknown sessions — never raises for a
        missing blob (matches :class:`SQLiteMemoryStore`). Hits the
        in-process cache first; falls through to Drive on miss or
        TTL expiry.
        """
        if self._cache is not None:
            cached = self._cache.get(session_id)
            if cached is not None:
                return cached
        service = self._get_service()
        subfolder_id = self._resolve_subfolder(service, create_if_missing=False)
        if subfolder_id is None:
            return []
        file_id = self._find_blob_id(service, subfolder_id, session_id)
        if file_id is None:
            return []
        data = service.files().get_media(fileId=file_id).execute()
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
        messages = _parse_blob(text)
        if self._cache is not None and messages:
            self._cache.put(session_id, messages)
        return messages

    def search(self, query: str, limit: int = 5) -> list[Message]:
        """No-op for Drive backend.

        Drive has no native full-text search over JSON blob bodies.
        Implementers needing search should pair this store with a
        searchable index (Firestore, Elasticsearch, …) — see
        ``RFC-MEMORY-SEARCH-INDEX`` (deferred).
        """
        del query, limit
        logger.debug("GoogleDriveMemoryStore.search() returns empty — Drive has no native FTS")
        return []

    def list_sessions(self) -> list[str]:
        """Enumerate session IDs persisted to Drive."""
        service = self._get_service()
        subfolder_id = self._resolve_subfolder(service, create_if_missing=False)
        if subfolder_id is None:
            return []
        ids: list[str] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": (
                    f"'{subfolder_id}' in parents and mimeType = '{_MIME_TYPE}' and trashed = false"
                ),
                "fields": "nextPageToken, files(name)",
                "pageSize": 100,
                "spaces": "drive",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.files().list(**kwargs).execute()
            for f in resp.get("files") or []:
                name = f.get("name") or ""
                if name.endswith(_FILE_EXT):
                    ids.append(name[: -len(_FILE_EXT)])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    def delete_session(self, session_id: str) -> None:
        """Delete a session's blob; no-op if missing.

        Also drops the cache entry so a subsequent ``load`` returns
        ``[]`` instead of stale-cached messages.
        """
        if self._cache is not None:
            self._cache.invalidate(session_id)
        service = self._get_service()
        subfolder_id = self._resolve_subfolder(service, create_if_missing=False)
        if subfolder_id is None:
            return
        file_id = self._find_blob_id(service, subfolder_id, session_id)
        if file_id is None:
            return
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

    def __repr__(self) -> str:
        return (
            f"GoogleDriveMemoryStore(folder_id={self.folder_id!r}, "
            f"subfolder={self.subfolder_name!r})"
        )

    # ---------------------------------------------------------------- internals

    def _write_session(self, session_id: str, messages: list[Message]) -> None:
        """Persist the full message list for a session as a single blob."""
        service = self._get_service()
        subfolder_id = self._resolve_subfolder(service, create_if_missing=True)
        assert subfolder_id is not None
        filename = f"{session_id}{_FILE_EXT}"
        body_json = _build_blob(session_id, messages)
        existing_id = self._find_blob_id(service, subfolder_id, session_id)
        if existing_id is None:
            self._create_blob(service, subfolder_id, filename, body_json)
        else:
            self._update_blob(service, existing_id, body_json)

    def _find_blob_id(
        self,
        service: Any,
        subfolder_id: str,
        session_id: str,
    ) -> str | None:
        """Look up the file id for a session blob, or None if missing."""
        filename = f"{session_id}{_FILE_EXT}"
        # Drive query string escaping: filenames are alnum + '-' + '_'
        # for our session ids; the surrounding quote is safe.
        q = f"'{subfolder_id}' in parents and name = '{filename}' and trashed = false"
        resp = (
            service.files()
            .list(
                q=q,
                fields="files(id, name)",
                pageSize=1,
                spaces="drive",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = resp.get("files") or []
        return str(files[0]["id"]) if files else None

    def _create_blob(
        self,
        service: Any,
        subfolder_id: str,
        filename: str,
        body_json: str,
    ) -> None:
        body = {
            "name": filename,
            "parents": [subfolder_id],
            "mimeType": _MIME_TYPE,
        }
        service.files().create(
            body=body,
            media_body=self._media(body_json),
            fields="id",
            supportsAllDrives=True,
        ).execute()

    def _update_blob(self, service: Any, file_id: str, body_json: str) -> None:
        service.files().update(
            fileId=file_id,
            media_body=self._media(body_json),
            supportsAllDrives=True,
        ).execute()

    @staticmethod
    def _media(body_json: str) -> Any:
        try:
            from googleapiclient.http import MediaInMemoryUpload
        except ImportError as exc:  # pragma: no cover — covered elsewhere
            raise ImportError(_missing_dep_message()) from exc
        return MediaInMemoryUpload(body_json.encode("utf-8"), mimetype=_MIME_TYPE)

    def _resolve_subfolder(
        self,
        service: Any,
        *,
        create_if_missing: bool,
    ) -> str | None:
        """Return the cached or freshly-discovered ``memory/`` subfolder id.

        ``create_if_missing=False`` for read paths (load/list/delete) so
        a never-written-to backend doesn't materialize an empty
        ``memory/`` folder just by being queried. Write paths (save)
        pass ``True``.
        """
        if self._subfolder_id is not None:
            return self._subfolder_id
        with self._subfolder_lock:
            if self._subfolder_id is not None:
                return self._subfolder_id
            existing = self._find_subfolder_id(service)
            if existing is not None:
                self._subfolder_id = existing
                return existing
            if not create_if_missing:
                return None
            self._subfolder_id = self._create_subfolder(service)
            return self._subfolder_id

    def _find_subfolder_id(self, service: Any) -> str | None:
        q = (
            f"'{self.folder_id}' in parents "
            f"and mimeType = '{_FOLDER_MIME}' "
            f"and name = '{self.subfolder_name}' "
            "and trashed = false"
        )
        resp = (
            service.files()
            .list(
                q=q,
                fields="files(id, name)",
                pageSize=1,
                spaces="drive",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = resp.get("files") or []
        return str(files[0]["id"]) if files else None

    def _create_subfolder(self, service: Any) -> str:
        body = {
            "name": self.subfolder_name,
            "parents": [self.folder_id],
            "mimeType": _FOLDER_MIME,
        }
        resp = (
            service.files()
            .create(
                body=body,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        return str(resp["id"])

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        with self._service_lock:
            if self._service is None:
                self._service = self._build_service()
            return self._service

    def _build_service(self) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ImportError(_missing_dep_message()) from exc

        creds = self._explicit_credentials
        if creds is None:
            try:
                from google.oauth2 import service_account
            except ImportError as exc:
                raise ImportError(_missing_dep_message()) from exc
            assert self._service_account_file is not None
            creds = service_account.Credentials.from_service_account_file(
                self._service_account_file,
                scopes=list(_DRIVE_SCOPES),
            )

        return build("drive", "v3", credentials=creds, cache_discovery=False)
