"""Wire uploaded sources into the chunk index and the Parquet table store.

Ingest writes two derived artifacts alongside the existing
``SourceRecord.text``:

* **chunks** — embedded passages in a :class:`DocumentIndexStore`, so a
  turn can retrieve the parts of a document that answer the question
  instead of carrying every document in the prompt.
* **Parquet tables** — one per sheet for spreadsheets and CSVs, so
  numeric questions are answered with SQL rather than by reading rows.

Everything here is optional and off by default. With
``GENERAL_CHAT_SOURCE_INDEX_ENABLED`` unset, :func:`index_source_record`
is a no-op and the application behaves exactly as it did before.

``record.text`` keeps being written either way, so the previous prompt
path stays available as a one-env-var rollback.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from general_chat.sources import SourceRecord, _safe_path_component

logger = logging.getLogger(__name__)

DEFAULT_TEXT_INDEX_MIN_CHARS = 2_000

#: This deployment has GOOGLE_API_KEY and no OPENAI_API_KEY, so the
#: provider is pinned rather than left to the SDK's OpenAI default.
DEFAULT_EMBEDDING_PROVIDER = "google"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
#: gemini-embedding-001 is natively 3072-dim; pgvector's HNSW index tops
#: out at 2000, so it is requested at 1536 via Matryoshka scaling.
DEFAULT_EMBEDDING_DIM = 1536

_UNSET = object()
_document_index: Any = _UNSET
_table_catalog: Any = _UNSET
#: Admin-managed backend selection: ``"pinecone"`` or ``None`` (SQL,
#: driven by the database URL). Seeded from the runtime settings at
#: startup and swapped by the admin PUT.
_vector_store_setting: str | None = None


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def source_index_enabled() -> bool:
    """Whether uploads should be chunked and embedded."""
    return _env_flag("GENERAL_CHAT_SOURCE_INDEX_ENABLED")


def table_parquet_enabled() -> bool:
    """Whether tabular uploads should be converted to Parquet."""
    return _env_flag("GENERAL_CHAT_TABLE_PARQUET_ENABLED", default=source_index_enabled())


def storage_root() -> Path:
    """Root the example uses for its own state."""
    from general_chat.agent import get_persona_dir

    default_root = get_persona_dir().parent / ".openbench"
    return Path(os.getenv("GENERAL_CHAT_STORAGE_ROOT", str(default_root)))


def table_root() -> Path:
    """Directory holding Parquet files.

    Deliberately outside ``uploads/``: the turn-end cleanup
    (``_cleanup_source_uploads_after_use``) deletes uploaded files after
    they are used, and the Parquet copies must survive that.
    """
    return storage_root() / "tables"


def _database_url() -> str | None:
    return os.getenv("OPENBENCH_DOC_INDEX_URL") or os.getenv("GENERAL_CHAT_DATABASE_URL") or None


def set_vector_store(value: str | None) -> None:
    """Apply the admin-managed ``vector_store`` selection.

    ``"pinecone"`` routes index construction to the Pinecone backend;
    any other value keeps the SQL selection driven by the database URL.
    The cached index is dropped only when the selection actually changes,
    so a startup seed with the current value never tears down a live
    index. The Parquet table catalog is untouched — it is not a vector
    store.
    """
    global _vector_store_setting, _document_index
    normalized = value if value == "pinecone" else None
    if normalized == _vector_store_setting:
        return
    _vector_store_setting = normalized
    _document_index = _UNSET


def get_document_index() -> Any:
    """Process-wide document index, or ``None`` when disabled.

    Built once and cached, including the ``None`` result, so a
    misconfigured deployment does not retry construction on every upload.
    """
    global _document_index
    if _document_index is not _UNSET:
        return _document_index

    if not source_index_enabled():
        _document_index = None
        return None

    try:
        from openbench.data.stores.document_index import build_document_index

        _document_index = build_document_index(
            database_url=_database_url(),
            storage_root=storage_root(),
            vector_backend=_vector_store_setting,
            # Default to Google explicitly. Without a provider name the SDK
            # resolver falls through to OpenAI, and this deployment has a
            # GOOGLE_API_KEY but no OPENAI_API_KEY.
            embedding_provider_name=(
                os.getenv("OPENBENCH_EMBEDDING_PROVIDER") or DEFAULT_EMBEDDING_PROVIDER
            ),
            embedding_model=(os.getenv("OPENBENCH_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL),
            # Must stay <= 2000: pgvector's HNSW index rejects more, and
            # gemini-embedding-001 defaults to 3072 unless asked otherwise.
            dimension=_env_int("OPENBENCH_EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM),
        )
    except Exception:
        logger.warning("Could not build the document index; sources stay unindexed", exc_info=True)
        _document_index = None
    return _document_index


def check_embeddings(*, log: bool = True) -> dict[str, Any] | None:
    """Probe the embedding provider once, at startup.

    A bad key or a dimension mismatch would otherwise surface only as a
    silent ``indexStatus=failed`` on every upload, which is far harder to
    diagnose than one explicit line in the container log.

    Returns ``None`` when the index is disabled; never raises.
    """
    index = get_document_index()
    if index is None:
        return None

    result = index.check_embeddings()
    if not log:
        return result

    if result.get("ok"):
        logger.info(
            "[general-chat] embeddings ready: provider=%s model=%s dim=%s",
            result.get("provider"),
            result.get("model"),
            result.get("actual_dimension"),
        )
    else:
        logger.error(
            "[general-chat] EMBEDDINGS UNAVAILABLE — uploads will not be indexed. "
            "provider=%s model=%s expected_dim=%s: %s",
            result.get("provider"),
            result.get("model"),
            result.get("expected_dimension"),
            result.get("error"),
        )
    return result


def get_table_catalog() -> Any:
    """Process-wide Parquet table catalog, or ``None`` when disabled."""
    global _table_catalog
    if _table_catalog is not _UNSET:
        return _table_catalog

    if not table_parquet_enabled():
        _table_catalog = None
        return None

    try:
        from openbench.data.tabular.catalog import build_table_catalog

        _table_catalog = build_table_catalog(
            database_url=_database_url(), storage_root=storage_root()
        )
    except Exception:
        logger.warning("Could not build the table catalog; tables stay unconverted", exc_info=True)
        _table_catalog = None
    return _table_catalog


def reset_caches() -> None:
    """Drop the cached index and catalog. For tests and env changes."""
    global _document_index, _table_catalog
    _document_index = _UNSET
    _table_catalog = _UNSET


def _parquet_dir(record: SourceRecord) -> Path:
    return (
        table_root()
        / _safe_path_component(record.owner or "local")
        / _safe_path_component(record.session_id or "session")
        / _safe_path_component(record.id)
    )


def _local_path_for(record: SourceRecord, stored_file: Any = None) -> str | None:
    """Best available on-disk path for the uploaded file."""
    path = getattr(stored_file, "path", None)
    if path and Path(path).is_file():
        return str(path)
    metadata = record.metadata or {}
    candidate = metadata.get("localFilePath")
    if isinstance(candidate, str) and Path(candidate).is_file():
        return candidate
    return None


def _index_tables(record: SourceRecord, stored_file: Any) -> list[dict[str, Any]]:
    """Convert a tabular source to Parquet and catalog the results."""
    catalog = get_table_catalog()
    if catalog is None:
        return []

    from openbench.data.tabular.converter import convert_to_parquet, is_tabular_file

    if not is_tabular_file(record.name, record.mime_type):
        return []

    path = _local_path_for(record, stored_file)
    if path is None:
        logger.info("Source %s has no local file to convert to Parquet", record.id)
        return []

    destination = _parquet_dir(record)
    artifacts = convert_to_parquet(
        path, dest_dir=destination, source_id=record.id, compression="zstd"
    )

    summaries: list[dict[str, Any]] = []
    for artifact in artifacts:
        catalog.upsert(artifact, session_id=record.session_id, owner=record.owner)
        summaries.append(
            {
                "table": artifact.name,
                "displayName": artifact.display_name,
                "rowCount": artifact.row_count,
                "columnCount": len(artifact.columns),
                "schemaCard": artifact.schema_card(),
            }
        )
    return summaries


def _index_text(record: SourceRecord) -> dict[str, Any] | None:
    """Chunk and embed a source's extracted text."""
    index = get_document_index()
    if index is None:
        return None

    text = record.text or ""
    minimum = _env_int("GENERAL_CHAT_SOURCE_INDEX_MIN_CHARS", DEFAULT_TEXT_INDEX_MIN_CHARS)
    if len(text.strip()) < minimum:
        # Short sources are cheaper to carry whole on the card than to
        # index, retrieve, and cite.
        return None

    return index.index_text(
        text,
        source_id=record.id,
        session_id=record.session_id,
        owner=record.owner,
        name=record.name,
        kind=record.kind,
        url=record.url or "",
    )


def index_source_record(record: SourceRecord, *, stored_file: Any = None) -> SourceRecord:
    """Index a parsed source, recording the outcome on its metadata.

    Mutates and returns ``record``. Never raises: indexing is an
    enhancement, and a failure here must not cost the user their upload.
    The failure is recorded as ``indexStatus="failed"`` so the read path
    falls back to the previous full-text behaviour for that source.

    Args:
        record: A parsed :class:`SourceRecord`, already persisted or about
            to be.
        stored_file: The :class:`StoredFile` for the upload, when the
            caller has it — needed for Parquet conversion.

    Returns:
        The same record, with index metadata attached.
    """
    if not source_index_enabled():
        return record

    metadata = dict(record.metadata or {})
    if record.status != "ready":
        metadata["indexStatus"] = "skipped"
        record.metadata = metadata
        return record

    from datetime import datetime, timezone

    try:
        summary = _index_text(record)
        tables = _index_tables(record, stored_file)
    except Exception as exc:
        logger.warning("Indexing failed for source %s", record.id, exc_info=True)
        metadata["indexStatus"] = "failed"
        metadata["indexError"] = str(exc)
        record.metadata = metadata
        return record

    if summary is None and not tables:
        metadata["indexStatus"] = "skipped"
        record.metadata = metadata
        return record

    metadata["indexStatus"] = "ready"
    metadata.pop("indexError", None)
    metadata["indexedAt"] = datetime.now(timezone.utc).isoformat()

    if summary is not None:
        index = get_document_index()
        metadata["chunkCount"] = summary["chunk_count"]
        metadata["outline"] = (summary.get("outline") or [])[:40]
        try:
            metadata["summary"] = index.summarize_source(record.id)
        except Exception:
            metadata["summary"] = ""

    if tables:
        metadata["tables"] = tables

    record.metadata = metadata
    return record


def deindex_source(source_id: str, *, owner: str = "", session_id: str = "") -> None:
    """Delete every derived artifact belonging to a source.

    Chunks and Parquet files are copies of the user's data, so they must
    go when the source does. Idempotent and never raises: a delete route
    that fails because the index is unreachable would leave the user with
    content they cannot remove.

    Args:
        source_id: The source being deleted.
        owner: Owner key, used to locate the Parquet directory.
        session_id: Session id, used to locate the Parquet directory.
    """
    index = get_document_index()
    if index is not None:
        try:
            index.delete_source(source_id)
        except Exception:
            logger.warning("Could not delete chunks for source %s", source_id, exc_info=True)

    catalog = get_table_catalog()
    if catalog is not None:
        try:
            catalog.delete_source(source_id)
        except Exception:
            logger.warning("Could not delete table rows for source %s", source_id, exc_info=True)

    directory = (
        table_root()
        / _safe_path_component(owner or "local")
        / _safe_path_component(session_id or "session")
        / _safe_path_component(source_id)
    )
    try:
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        logger.warning("Could not delete Parquet files for source %s", source_id, exc_info=True)


def deindex_records(records: list) -> None:
    """Deindex a batch of records, using each one's own owner/session."""
    for record in records:
        source_id = getattr(record, "id", "")
        if not source_id:
            continue
        deindex_source(
            source_id,
            owner=getattr(record, "owner", "") or "",
            session_id=getattr(record, "session_id", "") or "",
        )


__all__ = [
    "check_embeddings",
    "deindex_records",
    "deindex_source",
    "get_document_index",
    "get_table_catalog",
    "index_source_record",
    "reset_caches",
    "source_index_enabled",
    "table_parquet_enabled",
    "table_root",
]
