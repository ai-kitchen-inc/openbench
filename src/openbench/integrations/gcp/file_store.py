"""Cloud Storage backed implementation of the chat ``FileStore`` protocol."""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.chat.files import StoredFile

logger = logging.getLogger(__name__)

__all__ = ["GCSFileStore", "GCSUploadSession"]

_DEFAULT_MIME = "application/octet-stream"
_APP_ID_KEY = "openbench_file_id"
_APP_MIME_KEY = "openbench_mime_type"
_APP_ORIGINAL_NAME_KEY = "openbench_original_name"
_APP_USER_ID_KEY = "openbench_user_id"
_APP_SESSION_ID_KEY = "openbench_session_id"
_APP_PURPOSE_KEY = "openbench_purpose"
CACHE_TTL_SECONDS = 60 * 60


@dataclass(frozen=True)
class GCSUploadSession:
    """Direct browser-to-GCS upload target returned by the API layer."""

    file_id: str
    bucket: str
    object_name: str
    upload_url: str
    method: str
    headers: dict[str, str]
    expires_in_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fileId": self.file_id,
            "bucket": self.bucket,
            "objectName": self.object_name,
            "uploadUrl": self.upload_url,
            "method": self.method,
            "headers": self.headers,
            "expiresInSeconds": self.expires_in_seconds,
        }


def _missing_dep_message() -> str:
    return (
        "GCSFileStore requires the 'gcp' extras. Install with:\n"
        "    pip install openbench[gcp]\n"
        "which pulls google-cloud-storage."
    )


class GCSFileStore:
    """FileStore implementation backed by Google Cloud Storage.

    Object layout:
    ``<prefix>/<user_id>/<session_id>/<file_id>/<safe_filename>``.
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        prefix: str,
        user_id: str = "default",
        session_id: str = "default",
        purpose: str = "uploads",
        cache_root: str | Path | None = None,
        client: Any | None = None,
    ):
        if not bucket_name:
            raise ValueError("bucket_name must be a non-empty string")
        if not prefix:
            raise ValueError("prefix must be a non-empty string")
        self.bucket_name = bucket_name
        self.prefix = _clean_prefix(prefix)
        self.user_id = _safe_path_component(user_id or "default")
        self.session_id = _safe_path_component(session_id or "default")
        self.purpose = purpose
        self._explicit_client = client
        self._client: Any = None
        if cache_root is None:
            import tempfile

            cache_root = Path(tempfile.gettempdir()) / "openbench-gcs-cache" / bucket_name
        self._cache_root = Path(cache_root) / self.prefix
        self._cache_root.mkdir(parents=True, exist_ok=True)

    def store(self, filename: str, content: bytes, mime_type: str) -> StoredFile:
        safe_name = Path(filename).name or "unnamed"
        mime = mime_type or _DEFAULT_MIME
        file_id = f"file-{uuid.uuid4().hex[:8]}"
        object_name = self.object_name_for(
            file_id=file_id,
            filename=safe_name,
            user_id=self.user_id,
            session_id=self.session_id,
        )
        blob = self._bucket().blob(object_name)
        blob.metadata = self._metadata(
            file_id=file_id,
            filename=safe_name,
            mime_type=mime,
            user_id=self.user_id,
            session_id=self.session_id,
        )
        blob.upload_from_string(content, content_type=mime)
        cache_path = self._cache_path(file_id, safe_name)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        return self._stored_from_blob(blob, file_id=file_id, cache_path=cache_path)

    def get(self, file_id: str) -> StoredFile | None:
        blob = self._find_blob(file_id)
        if blob is None:
            return None
        try:
            blob.reload()
        except Exception as exc:
            logger.debug("GCSFileStore.get(%s) reload failed: %s", file_id, exc)
            return None
        return self._stored_from_blob(blob, file_id=file_id)

    def get_local_path(self, file_id: str) -> str | None:
        self._gc_cache()
        blob = self._find_blob(file_id)
        if blob is None:
            return None
        try:
            blob.reload()
        except Exception as exc:
            logger.warning("GCSFileStore: metadata lookup failed for %s: %s", file_id, exc)
            return None
        name = _blob_original_name(blob) or Path(blob.name).name or "unnamed"
        cache_path = self._cache_path(file_id, name)
        if cache_path.exists() and not self._is_stale(cache_path):
            os.utime(cache_path, None)
            return str(cache_path.absolute())
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            blob.download_to_filename(str(cache_path))
        except Exception as exc:
            logger.warning("GCSFileStore: download failed for %s: %s", file_id, exc)
            return None
        return str(cache_path.absolute())

    def delete(self, file_id: str) -> bool:
        blob = self._find_blob(file_id)
        if blob is None:
            return False
        try:
            blob.delete()
        except Exception as exc:
            logger.warning("GCSFileStore: delete failed for %s: %s", file_id, exc)
            return False
        cache_dir = self._cache_root / file_id
        if cache_dir.exists() and cache_dir.is_dir():
            for child in cache_dir.glob("*"):
                with suppress(OSError):
                    child.unlink()
            with suppress(OSError):
                cache_dir.rmdir()
        return True

    def create_resumable_upload_session(
        self,
        *,
        filename: str,
        mime_type: str,
        size_bytes: int | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        origin: str | None = None,
    ) -> GCSUploadSession:
        safe_name = Path(filename).name or "unnamed"
        mime = mime_type or _DEFAULT_MIME
        actual_user_id = _safe_path_component(user_id or self.user_id)
        actual_session_id = _safe_path_component(session_id or self.session_id)
        file_id = f"file-{uuid.uuid4().hex[:8]}"
        object_name = self.object_name_for(
            file_id=file_id,
            filename=safe_name,
            user_id=actual_user_id,
            session_id=actual_session_id,
        )
        blob = self._bucket().blob(object_name)
        blob.metadata = self._metadata(
            file_id=file_id,
            filename=safe_name,
            mime_type=mime,
            user_id=actual_user_id,
            session_id=actual_session_id,
        )
        kwargs: dict[str, Any] = {"content_type": mime}
        if size_bytes is not None:
            kwargs["size"] = size_bytes
        if origin:
            kwargs["origin"] = origin
        try:
            upload_url = blob.create_resumable_upload_session(**kwargs)
        except TypeError:
            upload_url = blob.create_resumable_upload_session(content_type=mime)
        return GCSUploadSession(
            file_id=file_id,
            bucket=self.bucket_name,
            object_name=object_name,
            upload_url=str(upload_url),
            method="PUT",
            headers={"Content-Type": mime},
        )

    def verify_uploaded_object(self, file_id: str) -> StoredFile | None:
        return self.get(file_id)

    def get_by_object(self, object_name: str) -> StoredFile | None:
        """Like :meth:`get` but addresses the blob by its exact object name.

        Avoids the ``list_blobs`` scan in :meth:`_find_blob`; use when the caller
        already knows the object path (e.g. a Cloud Storage finalize event).
        """
        if not object_name:
            return None
        blob = self._bucket().blob(object_name)
        try:
            blob.reload()
        except Exception as exc:
            logger.debug("GCSFileStore.get_by_object(%s) reload failed: %s", object_name, exc)
            return None
        file_id = _blob_file_id(blob) or _file_id_from_object_name(object_name) or object_name
        return self._stored_from_blob(blob, file_id=file_id)

    def get_local_path_for_object(self, object_name: str, file_id: str) -> str | None:
        """Download the exact object to the local cache (no ``list_blobs`` scan)."""
        if not object_name or not file_id:
            return None
        self._gc_cache()
        blob = self._bucket().blob(object_name)
        try:
            blob.reload()
        except Exception as exc:
            logger.warning("GCSFileStore: metadata lookup failed for %s: %s", object_name, exc)
            return None
        name = _blob_original_name(blob) or Path(blob.name).name or "unnamed"
        cache_path = self._cache_path(file_id, name)
        if cache_path.exists() and not self._is_stale(cache_path):
            os.utime(cache_path, None)
            return str(cache_path.absolute())
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            blob.download_to_filename(str(cache_path))
        except Exception as exc:
            logger.warning("GCSFileStore: download failed for %s: %s", object_name, exc)
            return None
        return str(cache_path.absolute())

    def object_name_for(
        self,
        *,
        file_id: str,
        filename: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        safe_user = _safe_path_component(user_id or self.user_id)
        safe_session = _safe_path_component(session_id or self.session_id)
        safe_name = Path(filename).name or "unnamed"
        return f"{self.prefix}/{safe_user}/{safe_session}/{file_id}/{safe_name}"

    def object_name_for_derived(
        self,
        *,
        file_id: str,
        filename: str = "extracted.md",
        user_id: str | None = None,
        session_id: str | None = None,
        derived_prefix: str = "derived",
    ) -> str:
        safe_user = _safe_path_component(user_id or self.user_id)
        safe_session = _safe_path_component(session_id or self.session_id)
        safe_name = Path(filename).name or "extracted.md"
        return f"{_clean_prefix(derived_prefix)}/{safe_user}/{safe_session}/{file_id}/{safe_name}"

    def upload_text_object(
        self,
        *,
        object_name: str,
        text: str,
        content_type: str = "text/markdown",
        metadata: dict[str, str] | None = None,
    ) -> None:
        blob = self._bucket().blob(object_name)
        blob.metadata = metadata or {}
        blob.upload_from_string(text.encode("utf-8"), content_type=content_type)

    def __repr__(self) -> str:
        return f"GCSFileStore(bucket_name={self.bucket_name!r}, prefix={self.prefix!r})"

    def _metadata(
        self,
        *,
        file_id: str,
        filename: str,
        mime_type: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, str]:
        return {
            _APP_ID_KEY: file_id,
            _APP_MIME_KEY: mime_type,
            _APP_ORIGINAL_NAME_KEY: filename,
            _APP_USER_ID_KEY: user_id,
            _APP_SESSION_ID_KEY: session_id,
            _APP_PURPOSE_KEY: self.purpose,
        }

    def _stored_from_blob(
        self,
        blob: Any,
        *,
        file_id: str,
        cache_path: Path | None = None,
    ) -> StoredFile:
        metadata = getattr(blob, "metadata", None) or {}
        name = metadata.get(_APP_ORIGINAL_NAME_KEY) or Path(blob.name).name or "unnamed"
        mime = metadata.get(_APP_MIME_KEY) or getattr(blob, "content_type", None) or _DEFAULT_MIME
        size = int(getattr(blob, "size", None) or 0)
        updated = getattr(blob, "updated", None)
        if updated is None:
            stored_at = datetime.now(timezone.utc).isoformat()
        elif hasattr(updated, "isoformat"):
            stored_at = updated.isoformat()
        else:
            stored_at = str(updated)
        local_path = cache_path or self._cache_path(file_id, name)
        return StoredFile(
            id=file_id,
            name=name,
            path=str(local_path.absolute()),
            mime_type=mime,
            size_bytes=size,
            stored_at=stored_at,
            web_view_link=f"gs://{self.bucket_name}/{blob.name}",
        )

    def _find_blob(self, file_id: str) -> Any | None:
        if not file_id:
            return None
        marker = f"/{file_id}/"
        try:
            for blob in self._bucket().list_blobs(prefix=f"{self.prefix}/"):
                if marker in f"/{blob.name}":
                    return blob
        except Exception as exc:
            logger.debug("GCSFileStore: list_blobs failed for %s: %s", file_id, exc)
            return None
        return None

    def _bucket(self) -> Any:
        return self._get_client().bucket(self.bucket_name)

    def _get_client(self) -> Any:
        if self._explicit_client is not None:
            return self._explicit_client
        if self._client is None:
            try:
                from google.cloud import storage
            except ImportError as exc:
                raise ImportError(_missing_dep_message()) from exc
            self._client = storage.Client()
        return self._client

    def _cache_path(self, file_id: str, name: str) -> Path:
        safe = Path(name).name or "unnamed"
        return self._cache_root / file_id / safe

    def _is_stale(self, path: Path) -> bool:
        try:
            return time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS
        except OSError:
            return True

    def _gc_cache(self) -> None:
        try:
            for child in self._cache_root.iterdir():
                if not child.is_dir():
                    continue
                files = list(child.glob("*"))
                if not files:
                    with suppress(OSError):
                        child.rmdir()
                    continue
                if all(self._is_stale(file) for file in files):
                    for file in files:
                        with suppress(OSError):
                            file.unlink()
                    with suppress(OSError):
                        child.rmdir()
        except OSError as exc:
            logger.debug("GCSFileStore: cache gc skipped: %s", exc)


def _clean_prefix(prefix: str) -> str:
    return prefix.strip().strip("/")


def _safe_path_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    return safe or "default"


def _blob_original_name(blob: Any) -> str | None:
    metadata = getattr(blob, "metadata", None) or {}
    value = metadata.get(_APP_ORIGINAL_NAME_KEY)
    return str(value) if value else None


def _blob_file_id(blob: Any) -> str | None:
    metadata = getattr(blob, "metadata", None) or {}
    value = metadata.get(_APP_ID_KEY)
    return str(value) if value else None


def _file_id_from_object_name(object_name: str) -> str | None:
    """Recover the ``file-...`` id from the ``.../<file_id>/<filename>`` path."""
    parts = [part for part in object_name.split("/") if part]
    for part in reversed(parts):
        if part.startswith("file-"):
            return part
    return None
