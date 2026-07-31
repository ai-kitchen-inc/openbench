"""Document chunk index with pgvector and SQLite backends.

Purpose-built for chat attachments: instead of pushing a whole document
into every prompt, ingest chunks it once and turns answer for a single
question into a top-k retrieval.

Two backends share one schema:

* :class:`PgVectorBackend` — Postgres with the ``vector`` extension for
  ANN search and a GIN full-text index for keyword search. When the
  extension is unavailable the store degrades to an array column plus a
  Python cosine scan rather than failing.
* :class:`SQLiteDocumentBackend` — local development and tests. Vectors
  live in a BLOB, keyword search uses FTS5 when the build supports it.

Both feed :class:`DocumentIndexStore`, which reuses the existing chunking,
embedding, and hybrid-rerank utilities so retrieval behaves the same way
it does for :class:`~openbench.data.stores.pinecone.PineconeStore`.
"""

from __future__ import annotations

import array
import json
import logging
import math
import os
import re
import sqlite3
import struct
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.core.abstractions import DataStore, Query, RawData, SearchResult
from openbench.data.stores.base import (
    Chunk,
    ChunkingConfig,
    EmbeddingMixin,
    HybridSearchMixin,
    chunk_text,
)
from openbench.data.stores.exceptions import StoreError

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_TABLE = "openbench_source_chunks"
DEFAULT_SQLITE_FILENAME = "source_index.sqlite3"

#: Candidate multiplier — each backend fetches this many times the
#: requested limit so the hybrid rerank has something to work with.
CANDIDATE_MULTIPLIER = 4

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _validate_identifier(name: str) -> str:
    """Guard table names before they are interpolated into SQL."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def _without_nul(value: str) -> str:
    """Strip NULs that Postgres TEXT/JSONB columns reject.

    Docling and several PDF extractors emit them; Postgres refuses the
    whole statement rather than the one bad character.
    """
    return value.replace("\x00", "�")


def _sanitize_json_value(value: Any) -> Any:
    """Recursively remove NUL characters from a JSON-serializable value."""
    if isinstance(value, str):
        return _without_nul(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {_without_nul(str(key)): _sanitize_json_value(item) for key, item in value.items()}
    return value


def _normalize(vector: list[float]) -> list[float]:
    """Scale a vector to unit length so dot product equals cosine.

    Matryoshka-truncated embeddings (e.g. gemini-embedding-001 reduced to
    1536 dims) are not unit length, so cosine comparisons need this.
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm <= 0:
        return list(vector)
    return [component / norm for component in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity, tolerant of unnormalized input."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _query_terms(text: str) -> list[str]:
    """Extract searchable word tokens from free-form query text.

    Punctuation is dropped rather than escaped: both FTS5 ``MATCH`` and
    ``plainto_tsquery`` treat stray operators as syntax errors.
    """
    return [term for term in _WORD_RE.findall(text or "") if term]


@dataclass
class ChunkRow:
    """One indexed chunk, as stored by every backend."""

    chunk_id: str
    source_id: str
    session_id: str
    owner: str
    chunk_index: int
    total_chunks: int
    content: str
    content_hash: str
    heading: str | None = None
    page: int | None = None
    sheet: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_item(self) -> dict[str, Any]:
        """Render as a ``SearchResult`` item.

        The ``{"id", "content", "metadata"}`` shape is what
        ``_AgentRAGMixin._retrieve_context`` expects.
        """
        metadata = dict(self.metadata)
        metadata.update(
            {
                "source_id": self.source_id,
                "session_id": self.session_id,
                "owner": self.owner,
                "chunk_index": self.chunk_index,
                "total_chunks": self.total_chunks,
                "content_hash": self.content_hash,
            }
        )
        if self.heading:
            metadata["heading"] = self.heading
        if self.page is not None:
            metadata["page"] = self.page
        if self.sheet:
            metadata["sheet"] = self.sheet
        return {"id": self.chunk_id, "content": self.content, "metadata": metadata}


class DocumentIndexBackend(ABC):
    """Storage engine for :class:`DocumentIndexStore`."""

    dialect: str = "unknown"

    @abstractmethod
    def ensure_schema(self, dimension: int) -> None:
        """Create tables and indexes if they do not exist."""

    @abstractmethod
    def upsert(self, rows: list[ChunkRow], vectors: list[list[float]]) -> int:
        """Insert or replace chunk rows with their embeddings."""

    @abstractmethod
    def existing_hashes(self, source_id: str) -> dict[int, str]:
        """Map ``chunk_index`` to ``content_hash`` for a stored source."""

    @abstractmethod
    def delete_source(self, source_id: str) -> int:
        """Delete every chunk of a source. Returns the row count."""

    @abstractmethod
    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a single chunk."""

    @abstractmethod
    def delete_chunks_from(self, source_id: str, first_index: int) -> int:
        """Delete chunks at or past ``first_index`` (orphans after a reindex)."""

    @abstractmethod
    def vector_search(
        self, vector: list[float], *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        """Nearest neighbours by cosine similarity, highest score first."""

    @abstractmethod
    def keyword_search(
        self, text: str, *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        """Full-text matches, highest score first."""

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> ChunkRow | None:
        """Fetch one chunk by id."""

    @abstractmethod
    def read_range(self, source_id: str, start: int, end: int) -> list[ChunkRow]:
        """Fetch chunks with ``start <= chunk_index < end``, in order."""

    @abstractmethod
    def headings(self, source_id: str) -> list[ChunkRow]:
        """Fetch every chunk of a source that carries a heading."""

    @abstractmethod
    def stats(self, *, filters: dict[str, Any]) -> dict[str, Any]:
        """Row and source counts for the filtered scope."""

    def close(self) -> None:  # noqa: B027 - optional hook, not every backend holds resources
        """Release backend resources. Optional."""


def _filter_clauses(filters: dict[str, Any], placeholder: str) -> tuple[str, list[Any]]:
    """Build a WHERE fragment from the supported filter keys.

    Supported: ``source_ids`` (list), ``source_id``, ``session_id``,
    ``owner``. Unknown keys are ignored rather than silently widening the
    scope in a way the caller cannot see.
    """
    clauses: list[str] = []
    params: list[Any] = []

    source_ids = filters.get("source_ids")
    if isinstance(source_ids, (list, tuple, set)):
        source_ids = [str(value) for value in source_ids]
        if not source_ids:
            # An explicit empty scope must match nothing, not everything.
            return " AND 1 = 0", []
        marks = ", ".join([placeholder] * len(source_ids))
        clauses.append(f"source_id IN ({marks})")
        params.extend(source_ids)
    elif filters.get("source_id"):
        clauses.append(f"source_id = {placeholder}")
        params.append(str(filters["source_id"]))

    if filters.get("session_id"):
        clauses.append(f"session_id = {placeholder}")
        params.append(str(filters["session_id"]))

    owner = filters.get("owner")
    if owner is not None:
        clauses.append(f"owner = {placeholder}")
        params.append(str(owner))

    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


class SQLiteDocumentBackend(DocumentIndexBackend):
    """SQLite backend for local development and tests.

    Vectors are stored as float32 BLOBs and scored in Python. Keyword
    search uses FTS5 when available and falls back to ``LIKE`` when the
    SQLite build lacks it.
    """

    dialect = "sqlite"

    _COLUMNS = (
        "chunk_id, source_id, session_id, owner, chunk_index, total_chunks, "
        "content, content_hash, heading, page, sheet, metadata"
    )

    def __init__(self, db_path: str | Path, *, table_name: str = DEFAULT_CHUNK_TABLE) -> None:
        self.db_path = str(db_path)
        self.table_name = _validate_identifier(table_name)
        self.fts_table = f"{self.table_name}_fts"
        self._fts_enabled = False
        parent = Path(self.db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self):
        """Open a connection, commit on success, and always close it.

        ``sqlite3``'s own context manager commits but leaves the handle
        open, which leaks descriptors and keeps the database file locked
        on Windows.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ensure_schema(self, dimension: int) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT '',
                    chunk_index INTEGER NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    heading TEXT,
                    page INTEGER,
                    sheet TEXT,
                    metadata TEXT NOT NULL DEFAULT '{{}}',
                    embedding BLOB,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{self.table_name}_source_chunk "
                f"ON {self.table_name} (source_id, chunk_index)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_owner_session "
                f"ON {self.table_name} (owner, session_id)"
            )
            try:
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.fts_table} "
                    f"USING fts5(content, chunk_id UNINDEXED, tokenize='unicode61')"
                )
                self._fts_enabled = True
            except sqlite3.OperationalError:
                # SQLite built without FTS5 — hybrid_rerank's BM25 still
                # covers keyword relevance over the LIKE candidates.
                logger.warning("SQLite FTS5 unavailable; keyword search falls back to LIKE")
                self._fts_enabled = False

    @staticmethod
    def _pack(vector: list[float]) -> bytes:
        return array.array("f", vector).tobytes()

    @staticmethod
    def _unpack(blob: bytes | None) -> list[float]:
        if not blob:
            return []
        values = array.array("f")
        values.frombytes(blob)
        return list(values)

    def _row_to_chunk(self, row: sqlite3.Row) -> ChunkRow:
        metadata = row["metadata"]
        try:
            parsed = json.loads(metadata) if metadata else {}
        except (TypeError, ValueError):
            parsed = {}
        return ChunkRow(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            session_id=row["session_id"],
            owner=row["owner"],
            chunk_index=row["chunk_index"],
            total_chunks=row["total_chunks"],
            content=row["content"],
            content_hash=row["content_hash"],
            heading=row["heading"],
            page=row["page"],
            sheet=row["sheet"],
            metadata=parsed if isinstance(parsed, dict) else {},
        )

    def upsert(self, rows: list[ChunkRow], vectors: list[list[float]]) -> int:
        if not rows:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            (
                row.chunk_id,
                row.source_id,
                row.session_id,
                row.owner,
                row.chunk_index,
                row.total_chunks,
                row.content,
                row.content_hash,
                row.heading,
                row.page,
                row.sheet,
                json.dumps(row.metadata, ensure_ascii=False, default=str),
                self._pack(vector),
                now,
            )
            for row, vector in zip(rows, vectors, strict=True)
        ]
        with self._connect() as conn:
            conn.executemany(
                f"""
                INSERT INTO {self.table_name} (
                    chunk_id, source_id, session_id, owner, chunk_index, total_chunks,
                    content, content_hash, heading, page, sheet, metadata,
                    embedding, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    source_id = excluded.source_id,
                    session_id = excluded.session_id,
                    owner = excluded.owner,
                    chunk_index = excluded.chunk_index,
                    total_chunks = excluded.total_chunks,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    heading = excluded.heading,
                    page = excluded.page,
                    sheet = excluded.sheet,
                    metadata = excluded.metadata,
                    embedding = excluded.embedding
                """,
                payload,
            )
            if self._fts_enabled:
                ids = [row.chunk_id for row in rows]
                marks = ", ".join(["?"] * len(ids))
                conn.execute(f"DELETE FROM {self.fts_table} WHERE chunk_id IN ({marks})", ids)
                conn.executemany(
                    f"INSERT INTO {self.fts_table} (content, chunk_id) VALUES (?, ?)",
                    [(row.content, row.chunk_id) for row in rows],
                )
        return len(rows)

    def existing_hashes(self, source_id: str) -> dict[int, str]:
        with self._connect() as conn:
            cursor = conn.execute(
                f"SELECT chunk_index, content_hash FROM {self.table_name} WHERE source_id = ?",
                (source_id,),
            )
            return {int(row["chunk_index"]): row["content_hash"] for row in cursor.fetchall()}

    def _delete_fts(self, conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
        if not self._fts_enabled or not chunk_ids:
            return
        marks = ", ".join(["?"] * len(chunk_ids))
        conn.execute(f"DELETE FROM {self.fts_table} WHERE chunk_id IN ({marks})", chunk_ids)

    def delete_source(self, source_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                f"SELECT chunk_id FROM {self.table_name} WHERE source_id = ?", (source_id,)
            )
            chunk_ids = [row["chunk_id"] for row in cursor.fetchall()]
            if not chunk_ids:
                return 0
            conn.execute(f"DELETE FROM {self.table_name} WHERE source_id = ?", (source_id,))
            self._delete_fts(conn, chunk_ids)
            return len(chunk_ids)

    def delete_chunk(self, chunk_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(f"DELETE FROM {self.table_name} WHERE chunk_id = ?", (chunk_id,))
            self._delete_fts(conn, [chunk_id])
            return cursor.rowcount > 0

    def delete_chunks_from(self, source_id: str, first_index: int) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                f"SELECT chunk_id FROM {self.table_name} WHERE source_id = ? AND chunk_index >= ?",
                (source_id, first_index),
            )
            chunk_ids = [row["chunk_id"] for row in cursor.fetchall()]
            if not chunk_ids:
                return 0
            conn.execute(
                f"DELETE FROM {self.table_name} WHERE source_id = ? AND chunk_index >= ?",
                (source_id, first_index),
            )
            self._delete_fts(conn, chunk_ids)
            return len(chunk_ids)

    def vector_search(
        self, vector: list[float], *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        where, params = _filter_clauses(filters, "?")
        with self._connect() as conn:
            cursor = conn.execute(
                f"SELECT {self._COLUMNS}, embedding FROM {self.table_name} WHERE 1 = 1{where}",
                params,
            )
            scored: list[tuple[ChunkRow, float]] = []
            for row in cursor.fetchall():
                stored = self._unpack(row["embedding"])
                if not stored:
                    continue
                scored.append((self._row_to_chunk(row), _cosine(vector, stored)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    def keyword_search(
        self, text: str, *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        terms = _query_terms(text)
        if not terms:
            return []
        where, params = _filter_clauses(filters, "?")
        with self._connect() as conn:
            if self._fts_enabled:
                # Rank in FTS first, then re-select with the scope filters
                # applied. Joining the virtual table directly would mean
                # rewriting column names into an alias — fragile and easy
                # to get subtly wrong.
                match = " OR ".join(f'"{term}"' for term in terms)
                try:
                    cursor = conn.execute(
                        f"SELECT chunk_id FROM {self.fts_table} "
                        f"WHERE {self.fts_table} MATCH ? "
                        f"ORDER BY bm25({self.fts_table}) LIMIT ?",
                        (match, limit * CANDIDATE_MULTIPLIER),
                    )
                    ranked_ids = [row["chunk_id"] for row in cursor.fetchall()]
                except sqlite3.OperationalError:
                    ranked_ids = []
                if ranked_ids:
                    marks = ", ".join(["?"] * len(ranked_ids))
                    rows = conn.execute(
                        f"SELECT {self._COLUMNS} FROM {self.table_name} "
                        f"WHERE chunk_id IN ({marks}){where}",
                        [*ranked_ids, *params],
                    ).fetchall()
                    order = {chunk_id: idx for idx, chunk_id in enumerate(ranked_ids)}
                    chunks = sorted(
                        (self._row_to_chunk(row) for row in rows),
                        key=lambda chunk: order.get(chunk.chunk_id, len(order)),
                    )
                    return [(chunk, 1.0) for chunk in chunks[:limit]]
                return []

            like_clauses = " OR ".join(["content LIKE ?"] * len(terms))
            like_params = [f"%{term}%" for term in terms]
            cursor = conn.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} "
                f"WHERE ({like_clauses}){where} LIMIT ?",
                [*like_params, *params, limit],
            )
            return [(self._row_to_chunk(row), 1.0) for row in cursor.fetchall()]

    def get_chunk(self, chunk_id: str) -> ChunkRow | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            return self._row_to_chunk(row) if row else None

    def read_range(self, source_id: str, start: int, end: int) -> list[ChunkRow]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} "
                f"WHERE source_id = ? AND chunk_index >= ? AND chunk_index < ? "
                f"ORDER BY chunk_index",
                (source_id, start, end),
            ).fetchall()
            return [self._row_to_chunk(row) for row in rows]

    def headings(self, source_id: str) -> list[ChunkRow]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} "
                f"WHERE source_id = ? AND heading IS NOT NULL AND heading != '' "
                f"ORDER BY chunk_index",
                (source_id,),
            ).fetchall()
            return [self._row_to_chunk(row) for row in rows]

    def stats(self, *, filters: dict[str, Any]) -> dict[str, Any]:
        where, params = _filter_clauses(filters, "?")
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS chunks, COUNT(DISTINCT source_id) AS sources "
                f"FROM {self.table_name} WHERE 1 = 1{where}",
                params,
            ).fetchone()
            return {
                "backend": self.dialect,
                "chunks": int(row["chunks"]),
                "sources": int(row["sources"]),
            }


class PgVectorBackend(DocumentIndexBackend):
    """Postgres backend using pgvector when the extension is available.

    ``vector_native`` reports whether the extension actually loaded. When
    it did not, embeddings live in a ``DOUBLE PRECISION[]`` column and
    similarity is computed in Python over the filtered candidate set —
    correct, just slower, and far better than refusing to start.
    """

    dialect = "postgres"

    _COLUMNS = (
        "chunk_id, source_id, session_id, owner, chunk_index, total_chunks, "
        "content, content_hash, heading, page, sheet, metadata"
    )

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = DEFAULT_CHUNK_TABLE,
    ) -> None:
        if not database_url and conn is None:
            raise ValueError("PgVectorBackend requires database_url or conn")
        self.database_url = database_url
        self._conn = conn
        self.table_name = _validate_identifier(table_name)
        self._vector_native = False
        self._dimension: int | None = None

    @property
    def vector_native(self) -> bool:
        """True when the pgvector extension is in use."""
        return self._vector_native

    @contextmanager
    def _connection(self):
        """Yield a connection, closing only the ones we opened."""
        if self._conn is not None:
            yield self._conn
            return
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError("PgVectorBackend requires psycopg. Install openbench[gcp].") from exc
        conn = psycopg.connect(str(self.database_url))
        try:
            yield conn
        finally:
            conn.close()

    def ensure_schema(self, dimension: int) -> None:
        self._dimension = dimension
        with self._connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    conn.commit()
                    self._vector_native = True
                except Exception as exc:
                    conn.rollback()
                    self._vector_native = False
                    logger.warning(
                        "pgvector unavailable (%s); document index running in degraded scan mode",
                        exc,
                    )

            embedding_type = f"vector({dimension})" if self._vector_native else "DOUBLE PRECISION[]"
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        chunk_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        owner TEXT NOT NULL DEFAULT '',
                        chunk_index INTEGER NOT NULL,
                        total_chunks INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        heading TEXT,
                        page INTEGER,
                        sheet TEXT,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding {embedding_type},
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{self.table_name}_source_chunk "
                    f"ON {self.table_name} (source_id, chunk_index)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_owner_session "
                    f"ON {self.table_name} (owner, session_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_source "
                    f"ON {self.table_name} (source_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_fts "
                    f"ON {self.table_name} USING GIN (to_tsvector('simple', content))"
                )
            conn.commit()

            if self._vector_native:
                # HNSW build can fail on very old pgvector; the table is
                # still usable with a sequential scan, so do not abort.
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_vec "
                            f"ON {self.table_name} USING hnsw (embedding vector_cosine_ops)"
                        )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Could not create HNSW index (%s); using sequential scan", exc)

    def _encode_vector(self, vector: list[float]) -> Any:
        if self._vector_native:
            return "[" + ",".join(f"{value:.7g}" for value in vector) + "]"
        return list(vector)

    @staticmethod
    def _decode_vector(value: Any) -> list[float]:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                return [float(part) for part in value.strip("[]").split(",") if part]
            except ValueError:
                return []
        if isinstance(value, (bytes, bytearray)):
            count = len(value) // 4
            return list(struct.unpack(f"{count}f", value[: count * 4]))
        return [float(item) for item in value]

    def _row_to_chunk(self, row: tuple) -> ChunkRow:
        metadata = row[11]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                metadata = {}
        return ChunkRow(
            chunk_id=row[0],
            source_id=row[1],
            session_id=row[2],
            owner=row[3],
            chunk_index=row[4],
            total_chunks=row[5],
            content=row[6],
            content_hash=row[7],
            heading=row[8],
            page=row[9],
            sheet=row[10],
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def upsert(self, rows: list[ChunkRow], vectors: list[list[float]]) -> int:
        if not rows:
            return 0
        cast = "::vector" if self._vector_native else "::double precision[]"
        with self._connection() as conn:
            with conn.cursor() as cur:
                for row, vector in zip(rows, vectors, strict=True):
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (
                            chunk_id, source_id, session_id, owner, chunk_index,
                            total_chunks, content, content_hash, heading, page,
                            sheet, metadata, embedding
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s{cast})
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            source_id = EXCLUDED.source_id,
                            session_id = EXCLUDED.session_id,
                            owner = EXCLUDED.owner,
                            chunk_index = EXCLUDED.chunk_index,
                            total_chunks = EXCLUDED.total_chunks,
                            content = EXCLUDED.content,
                            content_hash = EXCLUDED.content_hash,
                            heading = EXCLUDED.heading,
                            page = EXCLUDED.page,
                            sheet = EXCLUDED.sheet,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                        """,
                        (
                            row.chunk_id,
                            row.source_id,
                            row.session_id,
                            row.owner,
                            row.chunk_index,
                            row.total_chunks,
                            _without_nul(row.content),
                            row.content_hash,
                            _without_nul(row.heading) if row.heading else None,
                            row.page,
                            row.sheet,
                            json.dumps(
                                _sanitize_json_value(row.metadata), ensure_ascii=False, default=str
                            ),
                            self._encode_vector(vector),
                        ),
                    )
            conn.commit()
        return len(rows)

    def existing_hashes(self, source_id: str) -> dict[int, str]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT chunk_index, content_hash FROM {self.table_name} WHERE source_id = %s",
                (source_id,),
            )
            return {int(row[0]): row[1] for row in cur.fetchall()}

    def _execute_delete(self, sql: str, params: tuple) -> int:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                deleted = cur.rowcount
            conn.commit()
        return max(0, deleted)

    def delete_source(self, source_id: str) -> int:
        return self._execute_delete(
            f"DELETE FROM {self.table_name} WHERE source_id = %s", (source_id,)
        )

    def delete_chunk(self, chunk_id: str) -> bool:
        return (
            self._execute_delete(f"DELETE FROM {self.table_name} WHERE chunk_id = %s", (chunk_id,))
            > 0
        )

    def delete_chunks_from(self, source_id: str, first_index: int) -> int:
        return self._execute_delete(
            f"DELETE FROM {self.table_name} WHERE source_id = %s AND chunk_index >= %s",
            (source_id, first_index),
        )

    def vector_search(
        self, vector: list[float], *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        where, params = _filter_clauses(filters, "%s")
        with self._connection() as conn, conn.cursor() as cur:
            if self._vector_native:
                cur.execute(
                    f"SELECT {self._COLUMNS}, 1 - (embedding <=> %s::vector) AS score "
                    f"FROM {self.table_name} "
                    f"WHERE embedding IS NOT NULL{where} "
                    f"ORDER BY embedding <=> %s::vector LIMIT %s",
                    [self._encode_vector(vector), *params, self._encode_vector(vector), limit],
                )
                return [(self._row_to_chunk(row), float(row[12])) for row in cur.fetchall()]

            cur.execute(
                f"SELECT {self._COLUMNS}, embedding FROM {self.table_name} "
                f"WHERE embedding IS NOT NULL{where}",
                params,
            )
            scored = [
                (self._row_to_chunk(row), _cosine(vector, self._decode_vector(row[12])))
                for row in cur.fetchall()
            ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    def keyword_search(
        self, text: str, *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        terms = _query_terms(text)
        if not terms:
            return []
        where, params = _filter_clauses(filters, "%s")
        tsquery = " | ".join(terms)
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS}, "
                f"ts_rank(to_tsvector('simple', content), to_tsquery('simple', %s)) AS score "
                f"FROM {self.table_name} "
                f"WHERE to_tsvector('simple', content) @@ to_tsquery('simple', %s){where} "
                f"ORDER BY score DESC LIMIT %s",
                [tsquery, tsquery, *params, limit],
            )
            return [(self._row_to_chunk(row), float(row[12])) for row in cur.fetchall()]

    def get_chunk(self, chunk_id: str) -> ChunkRow | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} WHERE chunk_id = %s",
                (chunk_id,),
            )
            row = cur.fetchone()
            return self._row_to_chunk(row) if row else None

    def read_range(self, source_id: str, start: int, end: int) -> list[ChunkRow]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} "
                f"WHERE source_id = %s AND chunk_index >= %s AND chunk_index < %s "
                f"ORDER BY chunk_index",
                (source_id, start, end),
            )
            return [self._row_to_chunk(row) for row in cur.fetchall()]

    def headings(self, source_id: str) -> list[ChunkRow]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self.table_name} "
                f"WHERE source_id = %s AND heading IS NOT NULL AND heading <> '' "
                f"ORDER BY chunk_index",
                (source_id,),
            )
            return [self._row_to_chunk(row) for row in cur.fetchall()]

    def stats(self, *, filters: dict[str, Any]) -> dict[str, Any]:
        where, params = _filter_clauses(filters, "%s")
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT source_id) FROM {self.table_name} "
                f"WHERE 1 = 1{where}",
                params,
            )
            row = cur.fetchone()
        return {
            "backend": self.dialect,
            "chunks": int(row[0]) if row else 0,
            "sources": int(row[1]) if row else 0,
            "vector_native": self._vector_native,
        }


class DocumentIndexStore(DataStore, EmbeddingMixin, HybridSearchMixin):
    """Chunk-level document index backed by Postgres or SQLite.

    Example:
        >>> store = DocumentIndexStore(sqlite_path="./index.sqlite3")
        >>> store.index_text("...", source_id="source-1", session_id="s1")
        >>> store.search(Query(text="revenue", filters={"source_ids": ["source-1"]}))
    """

    def __init__(
        self,
        backend: DocumentIndexBackend | None = None,
        *,
        database_url: str | None = None,
        sqlite_path: str | Path | None = None,
        table_name: str = DEFAULT_CHUNK_TABLE,
        embedding_provider: Any = None,
        embedding_model: str | None = None,
        dimension: int | None = None,
        chunking: ChunkingConfig | None = None,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
        normalize_vectors: bool = True,
    ) -> None:
        if backend is None:
            if database_url:
                backend = PgVectorBackend(database_url, table_name=table_name)
            elif sqlite_path:
                backend = SQLiteDocumentBackend(sqlite_path, table_name=table_name)
            else:
                raise ValueError(
                    "DocumentIndexStore requires backend, database_url, or sqlite_path"
                )

        self.backend = backend
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._dimension = dimension
        self.chunking = chunking or ChunkingConfig()
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.normalize_vectors = normalize_vectors
        self._schema_ready = False

    @property
    def store_type(self) -> str:
        return "vector"

    def _ensure_schema(self) -> None:
        if not self._schema_ready:
            self.backend.ensure_schema(self._get_dimension())
            self._schema_ready = True

    def _vectors_for(self, texts: list[str]) -> list[list[float]]:
        vectors = self._embed_batch(texts)
        if self.normalize_vectors:
            return [_normalize(vector) for vector in vectors]
        return vectors

    def _vector_for(self, text: str) -> list[float]:
        vector = self._embed(text)
        return _normalize(vector) if self.normalize_vectors else vector

    # --- DataStore ABC ---------------------------------------------------

    def index(self, data: RawData, **options) -> str:
        """Index a ``RawData`` payload, deriving ids from its source/metadata."""
        if isinstance(data.content, bytes):
            text = data.content.decode("utf-8", errors="ignore")
        elif isinstance(data.content, str):
            text = data.content
        else:
            text = str(data.content)

        metadata = dict(data.metadata or {})
        source_id = (
            options.get("source_id")
            or metadata.get("source_id")
            or (data.source.source_id if data.source else None)
        )
        if not source_id:
            raise StoreError("index() requires a source_id in options, metadata, or data.source")

        result = self.index_text(
            text,
            source_id=str(source_id),
            session_id=str(options.get("session_id") or metadata.get("session_id") or ""),
            owner=str(options.get("owner") or metadata.get("owner") or ""),
            name=str(options.get("name") or metadata.get("name") or ""),
            kind=str(options.get("kind") or metadata.get("kind") or ""),
            url=str(options.get("url") or metadata.get("url") or ""),
            extra_metadata=metadata,
        )
        return str(result["source_id"])

    def search(self, query: Query) -> SearchResult:
        """Hybrid vector + keyword search over the filtered scope."""
        self._ensure_schema()
        text = query.text or ""
        filters = dict(query.filters or {})
        limit = max(1, int(query.limit or 10))
        candidates = limit * CANDIDATE_MULTIPLIER

        vector_hits: list[tuple[ChunkRow, float]] = []
        if query.vector:
            probe = _normalize(query.vector) if self.normalize_vectors else list(query.vector)
            vector_hits = self.backend.vector_search(probe, filters=filters, limit=candidates)
        elif text.strip():
            try:
                probe = self._vector_for(text)
                vector_hits = self.backend.vector_search(probe, filters=filters, limit=candidates)
            except Exception as exc:
                # Keyword search alone still answers the question; an
                # embedding outage should degrade, not fail the turn.
                logger.warning("Vector search unavailable (%s); using keyword search only", exc)

        keyword_hits: list[tuple[ChunkRow, float]] = []
        if text.strip():
            try:
                keyword_hits = self.backend.keyword_search(text, filters=filters, limit=candidates)
            except Exception as exc:
                logger.warning("Keyword search failed (%s)", exc)

        merged: dict[str, dict[str, Any]] = {}
        scores: dict[str, float] = {}
        for chunk, score in vector_hits:
            merged[chunk.chunk_id] = chunk.to_item()
            scores[chunk.chunk_id] = float(score)

        # A keyword-only hit has no vector score, but scoring it 0 would
        # bury it: the rerank weights vector similarity 0.7, so an exact
        # rare-term match could never outrank a semantically mediocre
        # chunk — defeating the reason hybrid search exists. Treat it as
        # the weakest vector candidate instead, and let its keyword score
        # do the deciding.
        vector_floor = min((score for _, score in vector_hits), default=0.0)
        for chunk, _ in keyword_hits:
            if chunk.chunk_id not in merged:
                merged[chunk.chunk_id] = chunk.to_item()
                scores[chunk.chunk_id] = float(vector_floor)

        if not merged:
            return SearchResult(
                items=[], total=0, scores=[], metadata={"backend": self.backend.dialect}
            )

        items = list(merged.values())
        item_scores = [scores[item["id"]] for item in items]
        ranked_items, ranked_scores = self.hybrid_rerank(
            items, item_scores, text, self.vector_weight, self.keyword_weight
        )
        return SearchResult(
            items=ranked_items[:limit],
            total=len(items),
            scores=ranked_scores[:limit],
            metadata={"backend": self.backend.dialect},
        )

    def get(self, item_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        chunk = self.backend.get_chunk(item_id)
        return chunk.to_item() if chunk else None

    def delete(self, item_id: str) -> bool:
        self._ensure_schema()
        return self.backend.delete_chunk(item_id)

    def update(self, item_id: str, data: Any) -> bool:
        """Replace a chunk's text and re-embed it."""
        self._ensure_schema()
        chunk = self.backend.get_chunk(item_id)
        if chunk is None:
            return False
        content = data if isinstance(data, str) else str(data)
        chunk.content = content
        chunk.content_hash = Chunk(
            id=item_id, content=content, index=chunk.chunk_index, total_chunks=chunk.total_chunks
        ).content_hash
        self.backend.upsert([chunk], self._vectors_for([content]))
        return True

    # --- Extensions ------------------------------------------------------

    def index_text(
        self,
        text: str,
        *,
        source_id: str,
        session_id: str,
        owner: str = "",
        name: str = "",
        kind: str = "",
        url: str = "",
        extra_metadata: dict[str, Any] | None = None,
        replace: bool = True,
    ) -> dict[str, Any]:
        """Chunk, embed, and store a document's text.

        Idempotent: chunks whose content hash already matches are skipped,
        so re-parsing an unchanged file costs no embedding calls.

        Returns:
            Summary dict with ``source_id``, ``chunk_count``, ``indexed``
            (chunks actually embedded), ``skipped``, ``deleted``, and
            ``outline``.
        """
        self._ensure_schema()
        pieces = chunk_text(text or "", self.chunking)
        if not pieces:
            deleted = self.backend.delete_source(source_id) if replace else 0
            return {
                "source_id": source_id,
                "chunk_count": 0,
                "indexed": 0,
                "skipped": 0,
                "deleted": deleted,
                "outline": [],
            }

        base_metadata = dict(extra_metadata or {})
        base_metadata.update({"name": name, "kind": kind, "url": url})
        total = len(pieces)

        existing = self.backend.existing_hashes(source_id) if replace else {}
        rows: list[ChunkRow] = []
        outline: list[dict[str, Any]] = []
        skipped = 0

        for idx, content in enumerate(pieces):
            chunk_id = f"{source_id}-chunk-{idx}"
            content_hash = Chunk(
                id=chunk_id, content=content, index=idx, total_chunks=total
            ).content_hash
            heading = _first_heading(content)
            if heading:
                outline.append({"heading": heading, "chunk_index": idx})
            if existing.get(idx) == content_hash:
                skipped += 1
                continue
            rows.append(
                ChunkRow(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    session_id=session_id,
                    owner=owner,
                    chunk_index=idx,
                    total_chunks=total,
                    content=content,
                    content_hash=content_hash,
                    heading=heading,
                    page=None,
                    sheet=None,
                    metadata=base_metadata,
                )
            )

        if rows:
            self.backend.upsert(rows, self._vectors_for([row.content for row in rows]))

        deleted = self.backend.delete_chunks_from(source_id, total) if replace else 0

        return {
            "source_id": source_id,
            "chunk_count": total,
            "indexed": len(rows),
            "skipped": skipped,
            "deleted": deleted,
            "outline": outline,
        }

    def delete_source(self, source_id: str) -> int:
        """Delete every chunk belonging to a source."""
        self._ensure_schema()
        return self.backend.delete_source(source_id)

    def read_range(
        self, source_id: str, start_index: int = 0, chunk_count: int = 4
    ) -> list[dict[str, Any]]:
        """Read consecutive chunks, for following up on a search hit."""
        self._ensure_schema()
        start = max(0, int(start_index))
        count = max(1, int(chunk_count))
        chunks = self.backend.read_range(source_id, start, start + count)
        return [chunk.to_item() for chunk in chunks]

    def outline(self, source_id: str) -> list[dict[str, Any]]:
        """List a source's headings with the chunk index each starts at."""
        self._ensure_schema()
        return [
            {
                "heading": chunk.heading,
                "chunk_index": chunk.chunk_index,
                "page": chunk.page,
            }
            for chunk in self.backend.headings(source_id)
        ]

    def summarize_source(self, source_id: str, max_chars: int = 400) -> str:
        """Return the opening text of a source, for its context card."""
        self._ensure_schema()
        chunks = self.backend.read_range(source_id, 0, 1)
        if not chunks:
            return ""
        content = " ".join(chunks[0].content.split())
        if len(content) <= max_chars:
            return content
        return content[:max_chars].rstrip() + "…"

    def stats(self, **filters: Any) -> dict[str, Any]:
        """Chunk and source counts for a filtered scope."""
        self._ensure_schema()
        return self.backend.stats(filters=filters)

    def close(self) -> None:
        self.backend.close()


def _first_heading(content: str) -> str | None:
    """Extract a markdown heading from the start of a chunk, if present."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        return None
    return None


def build_document_index(
    *,
    database_url: str | None = None,
    storage_root: str | Path | None = None,
    **kwargs: Any,
) -> DocumentIndexStore | None:
    """Build the appropriate index for the environment.

    Prefers Postgres when a database URL is available (explicit argument
    or ``OPENBENCH_DOC_INDEX_URL``), otherwise falls back to SQLite under
    ``storage_root``. Returns ``None`` when neither is configured, so
    callers can treat the index as an optional feature.
    """
    url = database_url or os.getenv("OPENBENCH_DOC_INDEX_URL") or None
    if url:
        return DocumentIndexStore(database_url=url, **kwargs)
    if storage_root:
        path = Path(storage_root) / DEFAULT_SQLITE_FILENAME
        return DocumentIndexStore(sqlite_path=path, **kwargs)
    return None


__all__ = [
    "CANDIDATE_MULTIPLIER",
    "DEFAULT_CHUNK_TABLE",
    "ChunkRow",
    "DocumentIndexBackend",
    "DocumentIndexStore",
    "PgVectorBackend",
    "SQLiteDocumentBackend",
    "build_document_index",
]
