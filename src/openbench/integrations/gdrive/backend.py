"""Google Drive :class:`StorageBackend` implementation.

Bundles :class:`GoogleDriveSessionStore`, :class:`GoogleDriveScratchpad`,
and :class:`GoogleDrivePersonaSource` behind a single auth + root-folder
config. Layout inside the root folder mirrors
:class:`~openbench.core.storage.LocalStorageBackend`::

    <root>/
    ├── sessions/     — session JSON files (GoogleDriveSessionStore)
    ├── memory/       — scratchpad .md files (GoogleDriveScratchpad)
    └── personas/
        └── <name>/   — SOUL/STYLE/AGENTS.md (GoogleDrivePersonaSource)

Subfolders are resolved lazily: ``session_store()`` only touches the
``sessions/`` subfolder, so using just one store doesn't pay for the
others. Resolution is "find-or-create" — existing folders are reused,
missing folders are created on demand.

Example:
    >>> from openbench.integrations.gdrive import GoogleDriveStorageBackend
    >>> backend = GoogleDriveStorageBackend(
    ...     root_folder_id="1ABCxyz...",
    ...     service_account_file="/secrets/lci-storage.json",
    ... )
    >>> sessions = backend.session_store()
    >>> pad = backend.scratchpad_store()
    >>> persona = backend.persona_source("lci-analyst")
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.chat.session_store import SessionStore
    from openbench.intelligence.persona_source import PersonaSource
    from openbench.intelligence.scratchpad import ScratchpadStore

logger = logging.getLogger(__name__)

__all__ = ["GoogleDriveStorageBackend"]

# Drive folder MIME type for "a folder".
_FOLDER_MIME = "application/vnd.google-apps.folder"

# Scopes: we both read (personas) and write (sessions, scratchpad).
_SCOPES = ("https://www.googleapis.com/auth/drive",)


def _missing_dep_message() -> str:
    return (
        "GoogleDriveStorageBackend requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]\n"
        "which pulls google-api-python-client and google-auth."
    )


class GoogleDriveStorageBackend:
    """Drive-backed :class:`StorageBackend` Protocol implementation.

    Attributes:
        root_folder_id: Id of the umbrella folder holding everything.
    """

    # Fixed subfolder names — hard-coded to match LocalStorageBackend.
    _SESSIONS_SUBFOLDER = "sessions"
    _MEMORY_SUBFOLDER = "memory"
    _PERSONAS_SUBFOLDER = "personas"
    _UPLOADS_SUBFOLDER = "uploads"
    _DOWNLOADS_SUBFOLDER = "downloads"

    def __init__(
        self,
        root_folder_id: str,
        *,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
        file_cache_root: str | Path | None = None,
    ):
        if not root_folder_id:
            raise ValueError("root_folder_id must be a non-empty string")
        if service_account_file is None and credentials is None:
            raise ValueError("Either service_account_file= or credentials= must be provided.")

        self.root_folder_id = root_folder_id
        self._service_account_file = (
            str(service_account_file) if service_account_file is not None else None
        )
        self._explicit_credentials = credentials
        # Cache dir for :class:`GoogleDriveFileStore`. Default to a
        # per-folder subdir under the OS tempdir so multiple users on
        # the same process don't collide.
        if file_cache_root is not None:
            self._file_cache_root = Path(file_cache_root)
        else:
            import tempfile as _tempfile

            self._file_cache_root = (
                Path(_tempfile.gettempdir()) / "openbench-drive-cache" / root_folder_id
            )

        # Lazy-built Drive service used only for subfolder resolution.
        self._service: Any = None
        self._service_lock = threading.Lock()
        # Cache resolved subfolder ids so repeat factory calls are cheap.
        # Keys are relative paths under the root — e.g. "sessions",
        # "personas/lci-analyst".
        self._subfolder_cache: dict[str, str] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------ Protocol

    def session_store(self) -> SessionStore:
        """Return a :class:`GoogleDriveSessionStore` rooted at ``<root>/sessions/``."""
        from openbench.integrations.gdrive.session_store import GoogleDriveSessionStore

        folder_id = self._resolve_subfolder(self._SESSIONS_SUBFOLDER)
        return GoogleDriveSessionStore(
            folder_id=folder_id,
            service_account_file=self._service_account_file,
            credentials=self._explicit_credentials,
        )

    def memory_store(self):
        """Return a memory store — Phase 1 fallback to local SQLite.

        Phase 2 of RFC-UNIFIED-MEMORY-STORAGE introduces a true
        :class:`GoogleDriveMemoryStore`. Until then, Drive-backed users
        get the same SQLite memory as non-Drive users — matching the
        pre-RFC hardcoded behaviour in lci-mini. Zero behaviour change
        for existing deployments.

        The returned path defaults to a per-process tempdir so multiple
        Drive-backed users on the same backend instance don't collide;
        lci-mini continues to manage its own SQLite path via
        ``LCI_MINI_MEMORY_DB`` until Phase 2 lands.
        """
        from openbench.intelligence.memory import LocalSQLiteMemoryStore

        return LocalSQLiteMemoryStore(db_path=str(self._fallback_memory_db_path()))

    def scratchpad_store(self) -> ScratchpadStore:
        """Return a :class:`GoogleDriveScratchpad` rooted at ``<root>/memory/``."""
        from openbench.integrations.gdrive.scratchpad import GoogleDriveScratchpad

        folder_id = self._resolve_subfolder(self._MEMORY_SUBFOLDER)
        return GoogleDriveScratchpad(
            folder_id=folder_id,
            service_account_file=self._service_account_file,
            credentials=self._explicit_credentials,
        )

    def file_store(self):
        """Return a :class:`GoogleDriveFileStore` rooted at ``<root>/uploads/``."""
        from openbench.integrations.gdrive.file_store import GoogleDriveFileStore

        folder_id = self._resolve_subfolder(self._UPLOADS_SUBFOLDER)
        return GoogleDriveFileStore(
            folder_id=folder_id,
            cache_root=self._file_cache_root / "uploads",
            service_account_file=self._service_account_file,
            credentials=self._explicit_credentials,
        )

    def output_store(self):
        """Return a :class:`GoogleDriveFileStore` rooted at ``<root>/downloads/``."""
        from openbench.integrations.gdrive.file_store import GoogleDriveFileStore

        folder_id = self._resolve_subfolder(self._DOWNLOADS_SUBFOLDER)
        return GoogleDriveFileStore(
            folder_id=folder_id,
            cache_root=self._file_cache_root / "downloads",
            service_account_file=self._service_account_file,
            credentials=self._explicit_credentials,
        )

    def persona_source(self, name: str = "default") -> PersonaSource:
        """Return a :class:`GoogleDrivePersonaSource` at ``<root>/personas/<name>/``."""
        if not name:
            raise ValueError("persona name must be a non-empty string")
        if "/" in name or "\\" in name:
            raise ValueError(
                f"persona name must be a flat identifier, got {name!r} "
                "(nested paths are not supported)"
            )
        from openbench.integrations.gdrive.drive_persona_source import GoogleDrivePersonaSource

        personas_root = self._resolve_subfolder(self._PERSONAS_SUBFOLDER)
        folder_id = self._resolve_subfolder(
            f"{self._PERSONAS_SUBFOLDER}/{name}", parent_id=personas_root
        )
        return GoogleDrivePersonaSource(
            folder_id=folder_id,
            service_account_file=self._service_account_file,
            credentials=self._explicit_credentials,
        )

    def __repr__(self) -> str:
        return f"GoogleDriveStorageBackend(root_folder_id={self.root_folder_id!r})"

    # ---------------------------------------------------------------- internals

    def _fallback_memory_db_path(self) -> Path:
        """Return the path for Phase 1's SQLite memory fallback.

        Until :class:`GoogleDriveMemoryStore` lands in Phase 2, every
        Drive-backed backend instance shares a single SQLite memory DB
        in the system tempdir, keyed by root folder id so two backends
        pointing at different Drive roots do not collide.
        """
        import tempfile

        safe_root = self.root_folder_id.replace("/", "_")
        path = Path(tempfile.gettempdir()) / f"openbench-memory-{safe_root}.db"
        return path

    def _resolve_subfolder(self, path: str, *, parent_id: str | None = None) -> str:
        """Return the Drive folder id for ``path``, creating it if missing.

        ``path`` is the cache key — pass ``"sessions"`` or
        ``"personas/lci-analyst"``. ``parent_id`` defaults to the root
        folder; pass an explicit id when resolving a grandchild of a
        non-root parent.
        """
        with self._cache_lock:
            cached = self._subfolder_cache.get(path)
            if cached is not None:
                return cached

        leaf_name = path.rsplit("/", 1)[-1]
        service = self._get_service()
        actual_parent = parent_id or self.root_folder_id

        folder_id = self._find_folder(service, leaf_name, actual_parent)
        if folder_id is None:
            folder_id = self._create_folder(service, leaf_name, actual_parent)

        with self._cache_lock:
            self._subfolder_cache[path] = folder_id
        return folder_id

    def _find_folder(self, service: Any, name: str, parent_id: str) -> str | None:
        query = (
            f"'{parent_id}' in parents "
            f"and name = '{name}' "
            f"and mimeType = '{_FOLDER_MIME}' "
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
        return str(files[0]["id"]) if files else None

    def _create_folder(self, service: Any, name: str, parent_id: str) -> str:
        body = {
            "name": name,
            "parents": [parent_id],
            "mimeType": _FOLDER_MIME,
        }
        resp = service.files().create(body=body, fields="id", supportsAllDrives=True).execute()
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
                scopes=list(_SCOPES),
            )

        return build("drive", "v3", credentials=creds, cache_discovery=False)
