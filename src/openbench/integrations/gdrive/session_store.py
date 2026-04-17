"""ChatSession persistence backed by a Google Drive folder.

Each session is stored as a single ``<session_id>.json`` file inside a
designated Drive folder. The full :class:`ChatSession` (including
messages, surfaces, attachments, timestamps) lives in the file body;
a lightweight summary (title, timestamps, message count, preview)
lives in ``appProperties`` so the sidebar's ``list()`` call can build
summaries without downloading every session.

``appProperties`` caveat: entries are scoped per (app / OAuth client).
If you later switch the service account or OAuth client, previously
written appProperties become invisible and :meth:`list` will report
blank titles/previews. The JSON body is always readable, so
:meth:`load` still works — only the sidebar fast-path degrades.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any

from openbench.chat.session import ChatSession, MessageRole
from openbench.chat.session_store import SessionStore, SessionSummary

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["GoogleDriveSessionStore"]

# Read/write is required — sessions are created and updated by the app.
_DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive",)

_FILE_EXT = ".json"
_MIME_TYPE = "application/json"

# appProperties keys. Drive caps values at 124 bytes per key, so we
# truncate preview aggressively.
_PROP_TITLE = "ob_title"
_PROP_CREATED = "ob_created_at"
_PROP_UPDATED = "ob_updated_at"
_PROP_COUNT = "ob_msg_count"
_PROP_PREVIEW = "ob_preview"
_PREVIEW_MAX = 100


def _missing_dep_message() -> str:
    return (
        "GoogleDriveSessionStore requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]\n"
        "which pulls google-api-python-client and google-auth."
    )


def _compute_preview(session: ChatSession) -> str:
    """First user message, single-lined and truncated for sidebar display."""
    for msg in session.messages:
        if msg.role == MessageRole.USER and msg.content:
            text = msg.content.strip().replace("\n", " ")
            if len(text) > _PREVIEW_MAX:
                return text[: _PREVIEW_MAX - 1] + "\u2026"
            return text
    return ""


def _build_app_properties(session: ChatSession) -> dict[str, str]:
    """Return the appProperties dict we stamp onto each session file."""
    return {
        _PROP_TITLE: session.title,
        _PROP_CREATED: session.created_at.isoformat(),
        _PROP_UPDATED: session.updated_at.isoformat(),
        _PROP_COUNT: str(len(session.messages)),
        _PROP_PREVIEW: _compute_preview(session),
    }


def _summary_from_file(file_dict: dict[str, Any]) -> SessionSummary | None:
    """Convert a Drive files.get response into a SessionSummary.

    Returns None if the filename or required appProperties are missing —
    corrupted / externally-edited entries are silently skipped by
    :meth:`list` rather than breaking the whole sidebar.
    """
    name = file_dict.get("name") or ""
    if not name.endswith(_FILE_EXT):
        return None
    session_id = name[: -len(_FILE_EXT)]
    props = file_dict.get("appProperties") or {}
    created = props.get(_PROP_CREATED)
    updated = props.get(_PROP_UPDATED)
    if not created or not updated:
        return None
    try:
        created_at = datetime.fromisoformat(created)
        updated_at = datetime.fromisoformat(updated)
        message_count = int(props.get(_PROP_COUNT) or 0)
    except (TypeError, ValueError):
        return None
    return SessionSummary(
        session_id=session_id,
        title=props.get(_PROP_TITLE) or session_id,
        created_at=created_at,
        updated_at=updated_at,
        message_count=message_count,
        preview=props.get(_PROP_PREVIEW) or "",
    )


class GoogleDriveSessionStore(SessionStore):
    """Store full ChatSessions as JSON files in a Drive folder.

    Constructor authentication (one must be provided):

    - ``service_account_file``: path to a service-account JSON key.
    - ``credentials``: a pre-built credentials object.

    The service account (or user) must have Editor access on the folder.
    """

    def __init__(
        self,
        folder_id: str,
        *,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
    ):
        if not folder_id:
            raise ValueError("folder_id must be a non-empty string")
        if service_account_file is None and credentials is None:
            raise ValueError("Either service_account_file= or credentials= must be provided.")

        self.folder_id = folder_id
        self._service_account_file = (
            str(service_account_file) if service_account_file is not None else None
        )
        self._explicit_credentials = credentials
        self._service: Any = None
        self._service_lock = threading.Lock()

    # ------------------------------------------------------------------ SessionStore

    def save(self, session: ChatSession) -> None:
        """Persist a session, overwriting any existing file with the same id."""
        service = self._get_service()
        filename = f"{session.session_id}{_FILE_EXT}"
        data_json = json.dumps(session.to_dict(), ensure_ascii=False)
        props = _build_app_properties(session)

        file_id = self._find_file_id(service, filename)
        if file_id is None:
            self._create(service, filename, data_json, props)
        else:
            self._update(service, file_id, data_json, props)

    def load(self, session_id: str) -> ChatSession | None:
        """Load a session by id; returns None if the file is absent."""
        service = self._get_service()
        file_id = self._find_file_id(service, f"{session_id}{_FILE_EXT}")
        if file_id is None:
            return None
        data = service.files().get_media(fileId=file_id).execute()
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
        try:
            return ChatSession.from_dict(json.loads(text))
        except (ValueError, KeyError) as exc:
            logger.warning("Ignoring corrupt session file %s (%s): %s", session_id, file_id, exc)
            return None

    def list(self, limit: int = 50, offset: int = 0) -> list[SessionSummary]:
        """List session summaries, newest-updated first.

        ``offset`` is implemented by iterating page tokens since Drive
        doesn't expose a native offset; keep ``offset=0`` whenever
        possible for the fast path.
        """
        if limit <= 0:
            return []
        service = self._get_service()
        query = f"'{self.folder_id}' in parents and mimeType = '{_MIME_TYPE}' and trashed = false"
        # Drive sorts by modifiedTime DESC which matches ``updated_at``
        # since we always refresh the file on save.
        results: list[SessionSummary] = []
        skipped = 0
        page_token: str | None = None
        # Ask for a slightly larger page so offset=N doesn't force us
        # through many tiny requests.
        page_size = min(100, offset + limit)
        while True:
            kwargs: dict[str, Any] = {
                "q": query,
                "fields": "nextPageToken, files(name, appProperties)",
                "orderBy": "modifiedTime desc",
                "pageSize": page_size,
                "spaces": "drive",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.files().list(**kwargs).execute()
            for f in resp.get("files") or []:
                summary = _summary_from_file(f)
                if summary is None:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                results.append(summary)
                if len(results) >= limit:
                    return results
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    def delete(self, session_id: str) -> None:
        """Delete a session's file; no-op if missing."""
        service = self._get_service()
        file_id = self._find_file_id(service, f"{session_id}{_FILE_EXT}")
        if file_id is None:
            return
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

    def __repr__(self) -> str:
        return f"GoogleDriveSessionStore(folder_id={self.folder_id!r})"

    # ---------------------------------------------------------------- internals

    def _find_file_id(self, service: Any, filename: str) -> str | None:
        query = f"'{self.folder_id}' in parents and name = '{filename}' and trashed = false"
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
        return str(files[0]["id"]) if files else None

    def _create(
        self,
        service: Any,
        filename: str,
        data_json: str,
        props: dict[str, str],
    ) -> None:
        body = {
            "name": filename,
            "parents": [self.folder_id],
            "mimeType": _MIME_TYPE,
            "appProperties": props,
        }
        service.files().create(
            body=body,
            media_body=self._media(data_json),
            fields="id",
            supportsAllDrives=True,
        ).execute()

    def _update(
        self,
        service: Any,
        file_id: str,
        data_json: str,
        props: dict[str, str],
    ) -> None:
        service.files().update(
            fileId=file_id,
            body={"appProperties": props},
            media_body=self._media(data_json),
            supportsAllDrives=True,
        ).execute()

    @staticmethod
    def _media(data_json: str) -> Any:
        try:
            from googleapiclient.http import MediaInMemoryUpload
        except ImportError as exc:  # pragma: no cover — covered elsewhere
            raise ImportError(_missing_dep_message()) from exc
        return MediaInMemoryUpload(data_json.encode("utf-8"), mimetype=_MIME_TYPE)

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
