"""Persistent catalog of Parquet tables derived from uploaded sources.

Mirrors the dual-backend shape of the document index: Postgres in
deployment, SQLite for local development, chosen by
:func:`build_table_catalog`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.data.tabular.converter import TableArtifact

logger = logging.getLogger(__name__)

DEFAULT_TABLE_CATALOG_TABLE = "openbench_source_tables"
DEFAULT_SQLITE_FILENAME = "source_tables.sqlite3"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> str:
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def _artifact_payload(artifact: TableArtifact) -> str:
    return json.dumps(artifact.to_dict(), ensure_ascii=False, default=str)


def _scope_clauses(
    *,
    source_ids: list[str] | None,
    session_id: str | None,
    owner: str | None,
    placeholder: str,
) -> tuple[str, list[Any]]:
    """Build a WHERE fragment for the supported scope filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if source_ids is not None:
        if not source_ids:
            return " AND 1 = 0", []
        marks = ", ".join([placeholder] * len(source_ids))
        clauses.append(f"source_id IN ({marks})")
        params.extend(str(value) for value in source_ids)

    if session_id:
        clauses.append(f"session_id = {placeholder}")
        params.append(str(session_id))

    if owner is not None:
        clauses.append(f"owner = {placeholder}")
        params.append(str(owner))

    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


class TableCatalog(ABC):
    """Storage for :class:`TableArtifact` metadata."""

    @abstractmethod
    def upsert(self, artifact: TableArtifact, *, session_id: str, owner: str = "") -> None:
        """Insert or replace a table's metadata."""

    @abstractmethod
    def list_for(
        self,
        *,
        source_ids: list[str] | None = None,
        session_id: str | None = None,
        owner: str | None = None,
    ) -> list[TableArtifact]:
        """List tables in a scope. ``source_ids=[]`` matches nothing."""

    @abstractmethod
    def get(self, table_id: str) -> TableArtifact | None:
        """Fetch one table by its id."""

    @abstractmethod
    def get_by_name(self, name: str) -> TableArtifact | None:
        """Fetch one table by its SQL alias."""

    @abstractmethod
    def delete_source(self, source_id: str) -> int:
        """Delete every table belonging to a source."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources. Optional."""


class SQLiteTableCatalog(TableCatalog):
    """SQLite-backed catalog for local development and tests."""

    def __init__(
        self, db_path: str | Path, *, table_name: str = DEFAULT_TABLE_CATALOG_TABLE
    ) -> None:
        self.db_path = str(db_path)
        self.table_name = _validate_identifier(table_name)
        parent = Path(self.db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    table_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    parquet_path TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    column_count INTEGER NOT NULL,
                    source_hash TEXT NOT NULL DEFAULT '',
                    schema TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_source "
                f"ON {self.table_name} (source_id)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_owner_session "
                f"ON {self.table_name} (owner, session_id)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_name ON {self.table_name} (name)"
            )

    @staticmethod
    def _to_artifact(row: sqlite3.Row) -> TableArtifact:
        return TableArtifact.from_dict(json.loads(row["schema"]))

    def upsert(self, artifact: TableArtifact, *, session_id: str, owner: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self.table_name} (
                    table_id, source_id, session_id, owner, name, display_name,
                    parquet_path, row_count, column_count, source_hash, schema, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(table_id) DO UPDATE SET
                    source_id = excluded.source_id,
                    session_id = excluded.session_id,
                    owner = excluded.owner,
                    name = excluded.name,
                    display_name = excluded.display_name,
                    parquet_path = excluded.parquet_path,
                    row_count = excluded.row_count,
                    column_count = excluded.column_count,
                    source_hash = excluded.source_hash,
                    schema = excluded.schema
                """,
                (
                    artifact.table_id,
                    artifact.source_id,
                    session_id,
                    owner,
                    artifact.name,
                    artifact.display_name,
                    artifact.parquet_path,
                    artifact.row_count,
                    len(artifact.columns),
                    artifact.source_hash,
                    _artifact_payload(artifact),
                    artifact.created_at or datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_for(
        self,
        *,
        source_ids: list[str] | None = None,
        session_id: str | None = None,
        owner: str | None = None,
    ) -> list[TableArtifact]:
        where, params = _scope_clauses(
            source_ids=source_ids, session_id=session_id, owner=owner, placeholder="?"
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT schema FROM {self.table_name} WHERE 1 = 1{where} ORDER BY created_at",
                params,
            ).fetchall()
            return [self._to_artifact(row) for row in rows]

    def get(self, table_id: str) -> TableArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT schema FROM {self.table_name} WHERE table_id = ?", (table_id,)
            ).fetchone()
            return self._to_artifact(row) if row else None

    def get_by_name(self, name: str) -> TableArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT schema FROM {self.table_name} WHERE name = ? ORDER BY created_at DESC",
                (name,),
            ).fetchone()
            return self._to_artifact(row) if row else None

    def delete_source(self, source_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self.table_name} WHERE source_id = ?", (source_id,)
            )
            return max(0, cursor.rowcount)


class PostgresTableCatalog(TableCatalog):
    """Postgres-backed catalog, self-migrating on first use."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = DEFAULT_TABLE_CATALOG_TABLE,
    ) -> None:
        if not database_url and conn is None:
            raise ValueError("PostgresTableCatalog requires database_url or conn")
        self.database_url = database_url
        self._conn = conn
        self.table_name = _validate_identifier(table_name)
        self._schema_ready = False

    @contextmanager
    def _connection(self):
        if self._conn is not None:
            yield self._conn
            return
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "PostgresTableCatalog requires psycopg. Install openbench[gcp]."
            ) from exc
        conn = psycopg.connect(str(self.database_url))
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        table_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        owner TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        parquet_path TEXT NOT NULL,
                        row_count BIGINT NOT NULL,
                        column_count INTEGER NOT NULL,
                        source_hash TEXT NOT NULL DEFAULT '',
                        schema JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_source "
                    f"ON {self.table_name} (source_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_owner_session "
                    f"ON {self.table_name} (owner, session_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_name "
                    f"ON {self.table_name} (name)"
                )
            conn.commit()
        self._schema_ready = True

    @staticmethod
    def _to_artifact(value: Any) -> TableArtifact:
        if isinstance(value, str):
            value = json.loads(value)
        return TableArtifact.from_dict(value)

    def upsert(self, artifact: TableArtifact, *, session_id: str, owner: str = "") -> None:
        self._ensure_schema()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        table_id, source_id, session_id, owner, name, display_name,
                        parquet_path, row_count, column_count, source_hash, schema
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (table_id) DO UPDATE SET
                        source_id = EXCLUDED.source_id,
                        session_id = EXCLUDED.session_id,
                        owner = EXCLUDED.owner,
                        name = EXCLUDED.name,
                        display_name = EXCLUDED.display_name,
                        parquet_path = EXCLUDED.parquet_path,
                        row_count = EXCLUDED.row_count,
                        column_count = EXCLUDED.column_count,
                        source_hash = EXCLUDED.source_hash,
                        schema = EXCLUDED.schema
                    """,
                    (
                        artifact.table_id,
                        artifact.source_id,
                        session_id,
                        owner,
                        artifact.name,
                        artifact.display_name,
                        artifact.parquet_path,
                        artifact.row_count,
                        len(artifact.columns),
                        artifact.source_hash,
                        _artifact_payload(artifact),
                    ),
                )
            conn.commit()

    def list_for(
        self,
        *,
        source_ids: list[str] | None = None,
        session_id: str | None = None,
        owner: str | None = None,
    ) -> list[TableArtifact]:
        self._ensure_schema()
        where, params = _scope_clauses(
            source_ids=source_ids, session_id=session_id, owner=owner, placeholder="%s"
        )
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT schema FROM {self.table_name} WHERE 1 = 1{where} ORDER BY created_at",
                params,
            )
            return [self._to_artifact(row[0]) for row in cur.fetchall()]

    def _fetch_one(self, column: str, value: str) -> TableArtifact | None:
        self._ensure_schema()
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT schema FROM {self.table_name} WHERE {column} = %s "
                f"ORDER BY created_at DESC LIMIT 1",
                (value,),
            )
            row = cur.fetchone()
            return self._to_artifact(row[0]) if row else None

    def get(self, table_id: str) -> TableArtifact | None:
        return self._fetch_one("table_id", table_id)

    def get_by_name(self, name: str) -> TableArtifact | None:
        return self._fetch_one("name", name)

    def delete_source(self, source_id: str) -> int:
        self._ensure_schema()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name} WHERE source_id = %s", (source_id,))
                deleted = cur.rowcount
            conn.commit()
        return max(0, deleted)


def build_table_catalog(
    *,
    database_url: str | None = None,
    storage_root: str | Path | None = None,
    table_name: str = DEFAULT_TABLE_CATALOG_TABLE,
) -> TableCatalog | None:
    """Build the appropriate catalog for the environment.

    Prefers Postgres when a URL is available (explicit argument or
    ``OPENBENCH_DOC_INDEX_URL``), otherwise SQLite under ``storage_root``.
    Returns ``None`` when neither is configured.
    """
    url = database_url or os.getenv("OPENBENCH_DOC_INDEX_URL") or None
    if url:
        return PostgresTableCatalog(url, table_name=table_name)
    if storage_root:
        return SQLiteTableCatalog(
            Path(storage_root) / DEFAULT_SQLITE_FILENAME, table_name=table_name
        )
    return None


__all__ = [
    "DEFAULT_TABLE_CATALOG_TABLE",
    "PostgresTableCatalog",
    "SQLiteTableCatalog",
    "TableCatalog",
    "build_table_catalog",
]
