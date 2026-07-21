"""Per-user database connections for Dashboard Chat.

Each user connects exactly one database via a SQLAlchemy URL. The URL
is stored as-is in ``db-connections.json`` under the storage root —
plaintext, acceptable for the local-dev scope of this example (the
README calls this out). Engines are cached per ``(username, url)`` and
invalidated whenever the stored URL changes.

Schema introspection returns structure only — table names, columns,
types, nullability, primary/foreign keys — never row data. That is the
entire database surface the LLM ever sees.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import sqlalchemy

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

_CONNECTIONS_FILENAME = "db-connections.json"
_SCHEMA_TABLE_CAP = 80


@dataclass(frozen=True)
class ConnectionRecord:
    username: str
    url: str
    dialect: str
    created_at: str


def normalize_driver(url: str) -> str:
    """Pick an installed DBAPI driver for bare postgres/mysql URLs.

    SQLAlchemy's ``postgresql://`` dialect defaults to psycopg2 and
    ``mysql://`` to MySQLdb. This repo ships psycopg v3 (and users often
    have pymysql instead of MySQLdb), so rewrite the drivername when the
    default is missing but a compatible driver is installed. Explicit
    ``+driver`` URLs pass through untouched.
    """
    import importlib.util

    try:
        parsed = sqlalchemy.engine.make_url(url)
    except Exception:
        return url
    if "+" in parsed.drivername:
        return url
    backend = parsed.get_backend_name()
    # str(URL) masks the password; render explicitly to keep it.
    if backend == "postgresql":
        if importlib.util.find_spec("psycopg2") is None and importlib.util.find_spec("psycopg"):
            return parsed.set(drivername="postgresql+psycopg").render_as_string(
                hide_password=False
            )
    elif (
        backend == "mysql"
        and importlib.util.find_spec("MySQLdb") is None
        and importlib.util.find_spec("pymysql")
    ):
        return parsed.set(drivername="mysql+pymysql").render_as_string(hide_password=False)
    return url


def normalize_sqlite_url(url: str, base_dir: Path) -> str:
    """Anchor a relative sqlite file path to ``base_dir``.

    ``sqlite:///sample.db`` resolves against the server process cwd,
    which depends on how the demo was launched. Pinning relative paths
    to the example root makes the README URL work from anywhere.
    Absolute paths and non-sqlite URLs pass through unchanged.
    """
    try:
        parsed = sqlalchemy.engine.make_url(url)
    except Exception:
        return url
    database = parsed.database or ""
    if parsed.get_backend_name() != "sqlite" or not database or database == ":memory:":
        return url
    from pathlib import Path as _Path

    if _Path(database).is_absolute():
        return url
    resolved = (base_dir / database).resolve()
    return str(parsed.set(database=resolved.as_posix()))


def redact_url(url: str) -> str:
    """Mask the password portion of a SQLAlchemy URL for API responses."""
    try:
        return sqlalchemy.engine.make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "***"


class ConnectionStore:
    """File-backed per-user connection registry with an engine cache."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._engines: dict[tuple[str, str], Engine] = {}

    def get(self, username: str) -> ConnectionRecord | None:
        record = self._load().get((username or "").strip().lower())
        if record is None:
            return None
        return ConnectionRecord(
            username=username,
            url=record["url"],
            dialect=record["dialect"],
            created_at=record["createdAt"],
        )

    def set(self, username: str, url: str) -> ConnectionRecord:
        normalized = (username or "").strip().lower()
        dialect = sqlalchemy.engine.make_url(url).get_backend_name()
        with self._lock:
            data = self._load()
            data[normalized] = {
                "url": url,
                "dialect": dialect,
                "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._save(data)
            self._evict_engine(normalized)
        return ConnectionRecord(
            username=normalized,
            url=url,
            dialect=dialect,
            created_at=data[normalized]["createdAt"],
        )

    def remove(self, username: str) -> None:
        normalized = (username or "").strip().lower()
        with self._lock:
            data = self._load()
            if normalized in data:
                del data[normalized]
                self._save(data)
            self._evict_engine(normalized)

    def engine_for(self, username: str) -> Engine | None:
        """Cached engine for the user's stored connection; None when unset."""
        record = self.get(username)
        if record is None:
            return None
        key = (record.username, record.url)
        engine = self._engines.get(key)
        if engine is None:
            with self._lock:
                engine = self._engines.get(key)
                if engine is None:
                    engine = _create_engine(record.url)
                    self._engines[key] = engine
        return engine

    def dispose_all(self) -> None:
        """Dispose every cached engine (used by tests and shutdown)."""
        with self._lock:
            for key in list(self._engines):
                with contextlib.suppress(Exception):
                    self._engines.pop(key).dispose()

    def _evict_engine(self, username: str) -> None:
        for key in [k for k in self._engines if k[0] == username]:
            with contextlib.suppress(Exception):
                self._engines.pop(key).dispose()

    def _load(self) -> dict[str, dict]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload.get("connections", {}))

    def _save(self, data: dict[str, dict]) -> None:
        payload = {"version": 1, "connections": data}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._path)


def _create_engine(url: str) -> Engine:
    url = normalize_driver(url)
    connect_args: dict = {}
    backend = sqlalchemy.engine.make_url(url).get_backend_name()
    if backend == "sqlite":
        # The engine is shared across request threads.
        connect_args["check_same_thread"] = False
    return sqlalchemy.create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        connect_args=connect_args,
    )


def test_connection(url: str) -> None:
    """Open the URL and run ``SELECT 1``; raises on any failure."""
    engine = _create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
    finally:
        engine.dispose()


def build_connection_store(storage_root: Path) -> ConnectionStore:
    return ConnectionStore(storage_root / _CONNECTIONS_FILENAME)


def introspect_schema(engine: Engine) -> dict:
    """Structure-only schema snapshot: tables, columns, types, PKs, FKs."""
    inspector = sqlalchemy.inspect(engine)
    tables = []
    for table_name in sorted(inspector.get_table_names()):
        pk_columns: set[str] = set()
        with contextlib.suppress(Exception):
            pk_columns = set(
                inspector.get_pk_constraint(table_name).get("constrained_columns") or []
            )
        columns = [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": bool(column.get("nullable", True)),
                "pk": column["name"] in pk_columns,
            }
            for column in inspector.get_columns(table_name)
        ]
        foreign_keys: list[dict] = []
        with contextlib.suppress(Exception):
            foreign_keys = [
                {
                    "columns": fk.get("constrained_columns") or [],
                    "refTable": fk.get("referred_table") or "",
                    "refColumns": fk.get("referred_columns") or [],
                }
                for fk in inspector.get_foreign_keys(table_name)
            ]
        tables.append({"name": table_name, "columns": columns, "foreignKeys": foreign_keys})
    return {"dialect": engine.dialect.name, "tables": tables}


def schema_as_text(schema: dict) -> str:
    """Token-light schema rendering for the LLM: one line per table."""
    lines = [f"dialect: {schema.get('dialect', 'unknown')}"]
    tables = schema.get("tables", [])
    for table in tables[:_SCHEMA_TABLE_CAP]:
        fk_by_column: dict[str, str] = {}
        for fk in table.get("foreignKeys", []):
            columns = fk.get("columns") or []
            ref_columns = fk.get("refColumns") or []
            for index, column in enumerate(columns):
                target_column = ref_columns[index] if index < len(ref_columns) else ""
                target = fk.get("refTable", "")
                fk_by_column[column] = f"{target}.{target_column}" if target_column else target
        parts = []
        for column in table.get("columns", []):
            piece = f"{column['name']} {column['type']}"
            if column.get("pk"):
                piece += " PK"
            if column["name"] in fk_by_column:
                piece += f" FK->{fk_by_column[column['name']]}"
            if not column.get("nullable", True) and not column.get("pk"):
                piece += " NOT NULL"
            parts.append(piece)
        lines.append(f"{table['name']}: {', '.join(parts)}")
    if len(tables) > _SCHEMA_TABLE_CAP:
        remaining = [table["name"] for table in tables[_SCHEMA_TABLE_CAP:]]
        lines.append(f"... {len(remaining)} more tables (columns omitted): {', '.join(remaining)}")
    return "\n".join(lines)
