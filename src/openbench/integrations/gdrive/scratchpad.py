"""User-editable scratchpad backed by a Google Drive folder.

Each scratchpad key maps to a ``<key>.md`` file in a single Drive
folder. The folder must already exist and the service account (or
user whose creds are passed) must have Editor access on it.

Example:
    >>> from openbench.integrations.gdrive import GoogleDriveScratchpad
    >>> pad = GoogleDriveScratchpad(
    ...     folder_id="1ABCxyz...",
    ...     service_account_file="/secrets/memory-writer.json",
    ... )
    >>> pad.write("default", "- user prefers Indonesian responses")
    >>> pad.read("default")
    '- user prefers Indonesian responses'

Limitations (v1):

- Keys must be **flat** — slashes are rejected so behavior stays
  predictable. Hierarchical keys (``"projects/q1"``) would require
  nested-folder resolution; defer until we have real demand.
- No caching. Every ``read`` / ``write`` / ``append`` round-trips to
  Drive so the agent and the user never see stale data from each
  other's edits. Wrap with a caching layer if throughput matters.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from openbench.intelligence.scratchpad import ScratchpadStore

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["GoogleDriveScratchpad"]

# Full-drive scope so we can create, update, list, and delete files
# inside a folder the user explicitly shares with us. ``drive.file`` is
# too restrictive here — it limits access to files this app created,
# which breaks any user-initiated edits to the same markdown.
_DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive",)

_FILE_EXT = ".md"
_MIME_TYPE = "text/markdown"


def _missing_dep_message() -> str:
    return (
        "GoogleDriveScratchpad requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]\n"
        "which pulls google-api-python-client and google-auth."
    )


def _validate_key(key: str) -> str:
    """Check a key is safe for use as a Drive filename.

    Raises:
        ValueError: For empty keys, NUL bytes, or slashes (hierarchical
            keys aren't supported yet).
    """
    if not key:
        raise ValueError("scratchpad key must be a non-empty string")
    if "\x00" in key:
        raise ValueError(f"scratchpad key contains a NUL byte: {key!r}")
    if "/" in key or "\\" in key:
        raise ValueError(
            f"hierarchical keys are not supported by GoogleDriveScratchpad "
            f"(got {key!r}); flatten with a different separator or use "
            f"LocalMarkdownScratchpad"
        )
    return key


class GoogleDriveScratchpad(ScratchpadStore):
    """ScratchpadStore that reads and writes markdown files in a Drive folder.

    Constructor authentication options (one must be provided):

    - ``service_account_file``: path to a service-account JSON key.
    - ``credentials``: a pre-built ``google.auth.credentials.Credentials``
      object.
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
        # Lazy — no network on construction.
        self._service: Any = None
        self._service_lock = threading.Lock()

    # ------------------------------------------------------------------ ScratchpadStore

    def read(self, key: str = "default") -> str:
        """Return the content of ``<key>.md``, or '' if the file is absent."""
        _validate_key(key)
        service = self._get_service()
        file_id = self._find_file_id(service, key)
        if file_id is None:
            return ""
        return self._download(service, file_id)

    def write(self, key: str, content: str) -> None:
        """Create or overwrite ``<key>.md`` in the folder."""
        _validate_key(key)
        service = self._get_service()
        file_id = self._find_file_id(service, key)
        if file_id is None:
            self._create(service, key, content)
        else:
            self._update(service, file_id, content)

    def append(self, key: str, content: str) -> None:
        """Append content to ``<key>.md``, creating it if absent.

        Existing content without a trailing newline gets one inserted so
        consecutive appends stay readable as distinct blocks — matches
        :class:`~openbench.intelligence.scratchpads.local_md.LocalMarkdownScratchpad`.
        """
        _validate_key(key)
        existing = self.read(key)
        if not existing:
            self.write(key, content)
            return
        separator = "" if existing.endswith("\n") else "\n"
        self.write(key, existing + separator + content)

    def list_keys(self) -> list[str]:
        """Return every scratchpad key in the folder, lexicographically sorted."""
        service = self._get_service()
        query = f"'{self.folder_id}' in parents and mimeType = '{_MIME_TYPE}' and trashed = false"
        names: list[str] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": query,
                "fields": "nextPageToken, files(name)",
                "spaces": "drive",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
                "pageSize": 100,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.files().list(**kwargs).execute()
            for f in resp.get("files") or []:
                name = f.get("name", "")
                if name.endswith(_FILE_EXT):
                    names.append(name[: -len(_FILE_EXT)])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return sorted(names)

    def delete(self, key: str) -> None:
        """Delete ``<key>.md`` if present; no-op otherwise."""
        _validate_key(key)
        service = self._get_service()
        file_id = self._find_file_id(service, key)
        if file_id is None:
            return
        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

    def __repr__(self) -> str:
        return f"GoogleDriveScratchpad(folder_id={self.folder_id!r})"

    # ---------------------------------------------------------------- internals

    def _find_file_id(self, service: Any, key: str) -> str | None:
        """Return the Drive file id for ``<key>.md`` in the folder, if any."""
        filename = f"{key}{_FILE_EXT}"
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
        if not files:
            return None
        return str(files[0]["id"])

    def _download(self, service: Any, file_id: str) -> str:
        data = service.files().get_media(fileId=file_id).execute()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    def _create(self, service: Any, key: str, content: str) -> None:
        body = {
            "name": f"{key}{_FILE_EXT}",
            "parents": [self.folder_id],
            "mimeType": _MIME_TYPE,
        }
        service.files().create(
            body=body,
            media_body=self._media(content),
            fields="id",
            supportsAllDrives=True,
        ).execute()

    def _update(self, service: Any, file_id: str, content: str) -> None:
        service.files().update(
            fileId=file_id,
            media_body=self._media(content),
            supportsAllDrives=True,
        ).execute()

    @staticmethod
    def _media(content: str) -> Any:
        """Build a ``MediaInMemoryUpload`` wrapping the UTF-8 encoded content.

        Lazy-imported so the module itself loads without the extras.
        """
        try:
            from googleapiclient.http import MediaInMemoryUpload
        except ImportError as exc:  # pragma: no cover — covered by other tests
            raise ImportError(_missing_dep_message()) from exc
        return MediaInMemoryUpload(content.encode("utf-8"), mimetype=_MIME_TYPE)

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
