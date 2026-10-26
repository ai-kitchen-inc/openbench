"""Persona backend backed by a Google Drive folder.

A Drive folder holds three sibling files — ``SOUL.md``, ``STYLE.md``,
``AGENTS.md`` — one per persona section. Missing files resolve to empty
strings for that section; callers never see an exception for a missing
section.

This is the folder-shaped counterpart of
:class:`~openbench.integrations.gdrive.persona_source.GoogleDocPersonaSource`,
which packs all three sections into a single Google Doc. Pick whichever
authoring shape your non-developer editors prefer.

Example:
    >>> from openbench.integrations.gdrive import GoogleDrivePersonaSource
    >>> from openbench.intelligence.persona import Persona
    >>> source = GoogleDrivePersonaSource(
    ...     folder_id="1ABCxyz...",
    ...     service_account_file="/secrets/persona-reader.json",
    ... )
    >>> persona = Persona.from_source(source)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from openbench.intelligence.persona_source import PersonaSource

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["GoogleDrivePersonaSource"]

# Read-only access to file metadata + content is sufficient.
_DRIVE_READONLY_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)

_FILE_MAP: dict[str, str] = {
    "soul": "SOUL.md",
    "style": "STYLE.md",
    "agents": "AGENTS.md",
}


def _missing_dep_message() -> str:
    return (
        "GoogleDrivePersonaSource requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]\n"
        "which pulls google-api-python-client and google-auth."
    )


class GoogleDrivePersonaSource(PersonaSource):
    """Fetch a Persona's sections from three markdown files in a Drive folder.

    Constructor authentication options (one must be provided):

    - ``service_account_file``: path to a service-account JSON key.
    - ``credentials``: a pre-built ``google.auth.credentials.Credentials``
      object.

    The service account (or user whose creds these are) must have at
    least Reader access on the target folder.
    """

    def __init__(
        self,
        folder_id: str,
        *,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
        cache_ttl: float = 300.0,
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
        self.cache_ttl = max(0.0, float(cache_ttl))

        # Lazy — no network on construction.
        self._service: Any = None
        self._service_lock = threading.Lock()
        # Cache parsed sections (not raw responses) for fast repeat fetches.
        self._cache: dict[str, str] | None = None
        self._cache_expires_at: float = 0.0
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------ PersonaSource

    def fetch(self, key: str) -> str:
        """Return the content for ``key`` (``soul``/``style``/``agents``)."""
        if key not in PersonaSource.KEYS:
            return ""
        sections = self._get_sections()
        return sections.get(key, "")

    def refresh(self) -> None:
        """Drop the in-memory cache so the next ``fetch`` re-hits Drive."""
        with self._cache_lock:
            self._cache = None
            self._cache_expires_at = 0.0

    def __repr__(self) -> str:
        return f"GoogleDrivePersonaSource(folder_id={self.folder_id!r})"

    # ---------------------------------------------------------------- internals

    def _get_sections(self) -> dict[str, str]:
        now = time.monotonic()
        with self._cache_lock:
            if self._cache is not None and self.cache_ttl > 0.0 and now < self._cache_expires_at:
                return self._cache

        sections = self._fetch_all_sections()

        with self._cache_lock:
            self._cache = sections
            self._cache_expires_at = now + self.cache_ttl
        return sections

    def _fetch_all_sections(self) -> dict[str, str]:
        """Fetch every section's markdown content from the Drive folder."""
        service = self._get_service()
        sections: dict[str, str] = {}
        for key, filename in _FILE_MAP.items():
            sections[key] = self._fetch_file_content(service, filename)
        return sections

    def _fetch_file_content(self, service: Any, filename: str) -> str:
        """Return ``filename``'s content from the folder, or '' if absent."""
        # Step 1: find the file id by (folder, name, non-trashed).
        query = f"'{self.folder_id}' in parents and name = '{filename}' and trashed = false"
        resp = (
            service.files()
            .list(
                q=query,
                fields="files(id, name, mimeType)",
                pageSize=1,
                spaces="drive",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = resp.get("files") or []
        if not files:
            return ""

        file_id = files[0]["id"]
        # Step 2: download the file's raw bytes and decode as UTF-8.
        data = service.files().get_media(fileId=file_id).execute()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace").strip()
        # Some client libs return str already.
        return str(data).strip()

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        with self._service_lock:
            if self._service is None:
                self._service = self._build_service()
            return self._service

    def _build_service(self) -> Any:
        """Lazy-import googleapiclient and build the ``drive`` service."""
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
                scopes=list(_DRIVE_READONLY_SCOPES),
            )

        return build("drive", "v3", credentials=creds, cache_discovery=False)
