"""Google-Drive-backed chat upload store.

Implements the :class:`FileStore` Protocol by uploading chat
attachments to the user's ``OpenBench/uploads/`` Drive folder. This
completes the "all data lives in the user's Drive" story: even
Excel/PDF files that a skill needs to parse are now owned by the
user, not cached on the server.

Performance: :meth:`get_local_path` maintains a short-lived on-disk
cache keyed by Drive file id so the xql skill, content extractor, and
subsequent chat turns don't re-download the same workbook on every
tool call.

The cache directory is best-effort cleanup: files older than
:data:`CACHE_TTL_SECONDS` are GC'd opportunistically on the next
access. The cache is process-local — multi-replica deployments
pay the download cost once per replica.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.chat.files import StoredFile

logger = logging.getLogger(__name__)

__all__ = ["GoogleDriveFileStore"]


# Drive app-property namespace so our records round-trip cleanly.
_APP_ID_KEY = "openbench_file_id"
_APP_MIME_KEY = "openbench_mime_type"
_DEFAULT_MIME = "application/octet-stream"

# Cache TTL — long enough to cover multi-turn XQL conversations without
# blowing out disk, short enough that a server reboot picks up fresh.
CACHE_TTL_SECONDS = 60 * 60  # 1 hour


def _missing_dep_message() -> str:
    return (
        "GoogleDriveFileStore requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]"
    )


class GoogleDriveFileStore:
    """FileStore that uploads to the user's Drive ``OpenBench/uploads/`` folder.

    Constructor authentication options (one must be provided):

    - ``service_account_file``: path to a service-account JSON key.
    - ``credentials``: a pre-built ``google.auth.credentials.Credentials``.

    Args:
        folder_id: Drive folder id of ``OpenBench/uploads/``.
        cache_root: Directory for the download-on-demand cache. Created
            if absent. Files older than :data:`CACHE_TTL_SECONDS` are
            GC'd opportunistically.
    """

    def __init__(
        self,
        folder_id: str,
        *,
        cache_root: str | Path,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
    ):
        if not folder_id:
            raise ValueError("folder_id must be a non-empty string")
        if service_account_file is None and credentials is None:
            raise ValueError("Either service_account_file= or credentials= must be provided.")

        self.folder_id = folder_id
        self._cache_root = Path(cache_root)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._service_account_file = (
            str(service_account_file) if service_account_file is not None else None
        )
        self._explicit_credentials = credentials
        self._service: Any = None

    # ------------------------------------------------------------------ FileStore

    def store(self, filename: str, content: bytes, mime_type: str) -> StoredFile:
        """Upload ``content`` to Drive and return metadata.

        The returned ``id`` is the Drive file id — lookups via
        :meth:`get` / :meth:`get_local_path` use that id.
        """
        service = self._get_service()
        safe_name = Path(filename).name or "unnamed"
        mime = mime_type or _DEFAULT_MIME

        # Mint an opaque public id so URLs don't leak Drive-specific
        # ids. We stash the mapping on the Drive file's appProperties.
        public_id = f"file-{uuid.uuid4().hex[:8]}"

        body = {
            "name": safe_name,
            "parents": [self.folder_id],
            "mimeType": mime,
            "appProperties": {
                _APP_ID_KEY: public_id,
                _APP_MIME_KEY: mime,
            },
        }
        resp = (
            service.files()
            .create(
                body=body,
                media_body=self._media(content, mime),
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        drive_file_id = str(resp["id"])
        self._gc_cache()

        # Pre-populate cache — caller almost always reads right after
        # store (content extractor runs inline).
        cache_path = self._cache_path(drive_file_id, safe_name)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)

        return StoredFile(
            id=drive_file_id,
            name=safe_name,
            path=str(cache_path.absolute()),
            mime_type=mime,
            size_bytes=len(content),
            stored_at=datetime.now(timezone.utc).isoformat(),
        )

    def get(self, file_id: str) -> StoredFile | None:
        """Fetch metadata for a previously-stored file."""
        service = self._get_service()
        try:
            meta = (
                service.files()
                .get(
                    fileId=file_id,
                    fields="id, name, mimeType, size, modifiedTime, appProperties",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:
            logger.debug("GoogleDriveFileStore.get(%s) failed: %s", file_id, exc)
            return None

        name = meta.get("name") or "unnamed"
        mime = (
            (meta.get("appProperties") or {}).get(_APP_MIME_KEY)
            or meta.get("mimeType")
            or _DEFAULT_MIME
        )
        size = int(meta.get("size") or 0)
        stored_at = meta.get("modifiedTime") or datetime.now(timezone.utc).isoformat()

        cache_path = self._cache_path(file_id, name)
        return StoredFile(
            id=file_id,
            name=name,
            path=str(cache_path.absolute()),
            mime_type=mime,
            size_bytes=size,
            stored_at=stored_at,
        )

    def get_local_path(self, file_id: str) -> str | None:
        """Return a local path for ``file_id``, downloading from Drive if needed.

        Cache-first: a recently-touched cached copy is returned
        immediately. Stale or missing entries trigger a Drive
        ``get_media`` call and refresh the cache.
        """
        service = self._get_service()
        self._gc_cache()

        # Look up metadata first so we know the filename.
        try:
            meta = (
                service.files()
                .get(fileId=file_id, fields="name, mimeType", supportsAllDrives=True)
                .execute()
            )
        except Exception as exc:
            logger.warning("GoogleDriveFileStore: file %s not found: %s", file_id, exc)
            return None
        name = meta.get("name") or "unnamed"

        cache_path = self._cache_path(file_id, name)
        if cache_path.exists() and not self._is_stale(cache_path):
            # Touch so gc keeps it alive.
            os.utime(cache_path, None)
            return str(cache_path.absolute())

        try:
            data = service.files().get_media(fileId=file_id).execute()
        except Exception as exc:
            logger.warning("GoogleDriveFileStore: download %s failed: %s", file_id, exc)
            return None
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            cache_path.write_bytes(data)
        else:
            cache_path.write_text(str(data), encoding="utf-8")
        return str(cache_path.absolute())

    def __repr__(self) -> str:
        return f"GoogleDriveFileStore(folder_id={self.folder_id!r})"

    # ---------------------------------------------------------------- internals

    def _cache_path(self, file_id: str, name: str) -> Path:
        """Return the on-disk cache path. One subdir per Drive id keeps
        filename collisions impossible across users / uploads."""
        safe = Path(name).name or "unnamed"
        return self._cache_root / file_id / safe

    def _is_stale(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return True
        return time.time() - mtime > CACHE_TTL_SECONDS

    def _gc_cache(self) -> None:
        """Best-effort cleanup of cached files past their TTL.

        Runs inline on store/get_local_path; keeps disk usage bounded
        without requiring a separate sweeper process.
        """
        try:
            for child in self._cache_root.iterdir():
                if not child.is_dir():
                    continue
                files = list(child.glob("*"))
                if not files:
                    try:
                        child.rmdir()
                    except OSError:
                        pass
                    continue
                if all(self._is_stale(f) for f in files):
                    for f in files:
                        try:
                            f.unlink()
                        except OSError:
                            pass
                    try:
                        child.rmdir()
                    except OSError:
                        pass
        except OSError as exc:  # pragma: no cover — defensive
            logger.debug("GoogleDriveFileStore: cache gc skipped: %s", exc)

    def _media(self, content: bytes, mime: str) -> Any:
        try:
            from googleapiclient.http import MediaInMemoryUpload
        except ImportError as exc:  # pragma: no cover — covered elsewhere
            raise ImportError(_missing_dep_message()) from exc
        return MediaInMemoryUpload(content, mimetype=mime or _DEFAULT_MIME)

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
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
                scopes=["https://www.googleapis.com/auth/drive.file"],
            )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
