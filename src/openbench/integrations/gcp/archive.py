"""Forever-persistent, date-partitioned archive for uploaded attachments.

Every file a user uploads is copied, best-effort, into a dedicated Cloud
Storage bucket under ``<prefix>/<YYYY-MM-DD>/<file-id>-<safe_name>``. Nothing
in the app ever deletes this prefix, so it is a permanent browsable record of
everything that was ever uploaded — independent of the live upload store, which
hard-deletes objects when a session or attachment is removed.

The archiver is intentionally decoupled from the primary storage backend: it is
gated on its own ``GENERAL_CHAT_ARCHIVE_BUCKET`` env var, not on
``GENERAL_CHAT_GCP_BUCKET``, so it works whether primary storage is local disk
or GCS. Archiving is always best-effort — a failure logs a warning and never
breaks or blocks a user upload.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["AttachmentArchiver"]

_DEFAULT_MIME = "application/octet-stream"
_DEFAULT_PREFIX = "archive"

# Blob custom-metadata keys (provenance, so a flat date folder stays traceable).
_META_ORIGINAL_NAME = "openbench_original_name"
_META_MIME = "openbench_mime_type"
_META_USER_ID = "openbench_user_id"
_META_SESSION_ID = "openbench_session_id"
_META_ARCHIVED_AT = "openbench_archived_at"


def _missing_dep_message() -> str:
    return (
        "AttachmentArchiver requires the 'gcp' extras. Install with:\n"
        "    pip install openbench[gcp]\n"
        "which pulls google-cloud-storage."
    )


def _safe_path_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)
    return safe or "unnamed"


class AttachmentArchiver:
    """Best-effort, append-only archive of uploaded files in Cloud Storage.

    Object layout: ``<prefix>/<YYYY-MM-DD>/<file-id>-<safe_filename>``.
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        prefix: str = _DEFAULT_PREFIX,
        client: Any | None = None,
    ):
        if not bucket_name:
            raise ValueError("bucket_name must be a non-empty string")
        self.bucket_name = bucket_name
        self.prefix = prefix.strip().strip("/") or _DEFAULT_PREFIX
        self._explicit_client = client
        self._client: Any = None

    @classmethod
    def from_env(cls) -> AttachmentArchiver | None:
        """Build from environment, or return ``None`` when the feature is off.

        Reads ``GENERAL_CHAT_ARCHIVE_BUCKET`` (the dedicated standalone archive
        bucket — there is deliberately no fallback to the uploads bucket) and
        ``GENERAL_CHAT_GCP_ARCHIVE_PREFIX`` (default ``archive``).
        """
        bucket_name = os.getenv("GENERAL_CHAT_ARCHIVE_BUCKET", "").strip()
        if not bucket_name:
            return None
        prefix = os.getenv("GENERAL_CHAT_GCP_ARCHIVE_PREFIX", _DEFAULT_PREFIX)
        return cls(bucket_name, prefix=prefix)

    def archive(
        self,
        filename: str,
        content: bytes,
        mime_type: str,
        *,
        user_id: str = "default",
        session_id: str = "default",
    ) -> str | None:
        """Copy ``content`` into the date-partitioned archive.

        Returns the ``gs://`` URI of the archived object, or ``None`` if the
        copy failed. Never raises — archiving must not break a user upload.
        """
        try:
            safe_name = _safe_path_component(Path(filename).name or "unnamed")
            mime = mime_type or _DEFAULT_MIME
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            file_id = f"file-{uuid.uuid4().hex[:8]}"
            object_name = f"{self.prefix}/{date}/{file_id}-{safe_name}"
            blob = self._bucket().blob(object_name)
            blob.metadata = {
                _META_ORIGINAL_NAME: Path(filename).name or "unnamed",
                _META_MIME: mime,
                _META_USER_ID: user_id or "default",
                _META_SESSION_ID: session_id or "default",
                _META_ARCHIVED_AT: datetime.now(timezone.utc).isoformat(),
            }
            blob.upload_from_string(content, content_type=mime)
            return f"gs://{self.bucket_name}/{object_name}"
        except Exception as exc:  # best-effort: never propagate
            logger.warning(
                "AttachmentArchiver: failed to archive %r (session=%s): %s",
                filename,
                session_id,
                exc,
            )
            return None

    def __repr__(self) -> str:
        return f"AttachmentArchiver(bucket_name={self.bucket_name!r}, prefix={self.prefix!r})"

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
