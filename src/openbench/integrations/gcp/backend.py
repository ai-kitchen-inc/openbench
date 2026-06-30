"""Google Cloud :class:`StorageBackend` implementation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openbench.core.storage import LocalStorageBackend

if TYPE_CHECKING:
    from openbench.chat.files import FileStore
    from openbench.chat.session_store import SessionStore
    from openbench.intelligence.memory import MemoryStore
    from openbench.intelligence.persona_source import PersonaSource
    from openbench.intelligence.scratchpad import ScratchpadStore

__all__ = ["GoogleCloudStorageBackend"]


class GoogleCloudStorageBackend:
    """Storage backend for GCE deployments.

    Files and generated outputs go to Cloud Storage. Sessions and agent
    memory go to PostgreSQL when ``database_url`` is provided; otherwise
    they fall back to a local backend for development and tests.
    """

    def __init__(
        self,
        *,
        bucket_name: str,
        database_url: str | None = None,
        user_id: str = "default",
        session_id: str = "default",
        uploads_prefix: str = "uploads",
        outputs_prefix: str = "outputs",
        derived_prefix: str = "derived",
        cache_root: str | Path | None = None,
        local_root: str | Path | None = None,
        storage_client: Any | None = None,
    ):
        if not bucket_name:
            raise ValueError("bucket_name must be a non-empty string")
        self.bucket_name = bucket_name
        self.database_url = database_url
        self.user_id = user_id
        self.session_id = session_id
        self.uploads_prefix = uploads_prefix
        self.outputs_prefix = outputs_prefix
        self.derived_prefix = derived_prefix
        self.cache_root = cache_root
        self._storage_client = storage_client
        if local_root is None:
            import tempfile

            local_root = Path(tempfile.gettempdir()) / "openbench-gcp-local"
        self._local = LocalStorageBackend(local_root)

    def session_store(self) -> SessionStore:
        if self.database_url:
            from openbench.integrations.gcp.session_store import PostgresSessionStore

            return PostgresSessionStore(self.database_url)
        return self._local.session_store()

    def memory_store(self) -> MemoryStore:
        if self.database_url:
            from openbench.integrations.gcp.memory_store import PostgresMemoryStore

            return PostgresMemoryStore(self.database_url)
        return self._local.memory_store()

    def scratchpad_store(self) -> ScratchpadStore:
        return self._local.scratchpad_store()

    def persona_source(self, name: str = "default") -> PersonaSource:
        return self._local.persona_source(name)

    def file_store(self) -> FileStore:
        from openbench.integrations.gcp.file_store import GCSFileStore

        return GCSFileStore(
            self.bucket_name,
            prefix=self.uploads_prefix,
            user_id=self.user_id,
            session_id=self.session_id,
            purpose="uploads",
            cache_root=self.cache_root,
            client=self._storage_client,
        )

    def output_store(self) -> FileStore:
        from openbench.integrations.gcp.file_store import GCSFileStore

        return GCSFileStore(
            self.bucket_name,
            prefix=self.outputs_prefix,
            user_id=self.user_id,
            session_id=self.session_id,
            purpose="outputs",
            cache_root=self.cache_root,
            client=self._storage_client,
        )

    @classmethod
    def from_env(cls, *, user_id: str = "default", session_id: str = "default"):
        bucket_name = os.environ["GENERAL_CHAT_GCP_BUCKET"]
        # When no Postgres is configured, sessions/memory fall back to a local
        # backend. Root it at the persistent storage volume
        # (GENERAL_CHAT_STORAGE_ROOT, e.g. the mounted /app-data/openbench) so
        # chat history survives container restarts instead of landing in an
        # ephemeral tempdir. Falls back to the tempdir default when unset.
        local_root = os.environ.get("GENERAL_CHAT_STORAGE_ROOT") or None
        return cls(
            bucket_name=bucket_name,
            database_url=os.environ.get("GENERAL_CHAT_DATABASE_URL"),
            user_id=user_id,
            session_id=session_id,
            uploads_prefix=os.environ.get("GENERAL_CHAT_GCP_UPLOADS_PREFIX", "uploads"),
            outputs_prefix=os.environ.get("GENERAL_CHAT_GCP_OUTPUTS_PREFIX", "outputs"),
            derived_prefix=os.environ.get("GENERAL_CHAT_GCP_DERIVED_PREFIX", "derived"),
            cache_root=os.environ.get("GENERAL_CHAT_GCP_CACHE_ROOT"),
            local_root=local_root,
        )

    def __repr__(self) -> str:
        return (
            "GoogleCloudStorageBackend("
            f"bucket_name={self.bucket_name!r}, user_id={self.user_id!r}, "
            f"session_id={self.session_id!r})"
        )
