"""Guarded read-only DuckDB SQL over Parquet tables.

The agent writes the SQL, so the SQL is untrusted input. Defence is
layered, and each layer is independently sufficient for the file-access
threat:

1. A text guard rejects anything that is not a single read-only
   statement, after stripping comments so keywords cannot hide behind
   ``--`` or ``/* */``.
2. The engine — never the model — materializes the in-scope Parquet
   files into a fresh in-memory database, then disables external access
   and locks the configuration. From that point the connection cannot
   read or write the filesystem regardless of what the query says.
   Tables too large to materialize stay as on-disk views; their exact
   directories are allowlisted via ``allowed_directories`` and external
   access is still disabled for every other path.
3. Results are capped by row count and by serialized size, so a
   ``SELECT *`` cannot recreate the context bloat this module exists to
   avoid.

``duckdb`` is imported inside functions so importing this module never
fails on an install without the ``tabular`` extra.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 1000
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MEMORY_LIMIT = "512MB"
DEFAULT_THREADS = 2
#: Above this row count a table is left as a Parquet view instead of
#: being copied into memory.
DEFAULT_MAX_MATERIALIZE_ROWS = 5_000_000
#: Serialized result payload cap, in characters.
DEFAULT_MAX_PAYLOAD_CHARS = 60_000

_ALLOWED_LEADING = frozenset({"select", "with", "describe", "summarize", "explain"})

_DENY_PATTERN = re.compile(
    r"\b("
    r"attach|detach|copy|export|import|install|load|pragma|"
    r"insert|update|delete|create|drop|alter|truncate|"
    r"call|set|reset|checkpoint|vacuum|shell|system|"
    r"read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|read_text|read_blob|"
    r"read_ndjson|read_ndjson_auto|read_json_objects|read_json_objects_auto|"
    r"read_ndjson_objects|sniff_csv|parquet_metadata|parquet_file_metadata|"
    r"parquet_kv_metadata|parquet_schema|"
    r"parquet_scan|csv_scan|json_scan|delta_scan|iceberg_scan|postgres_scan|"
    r"mysql_scan|sqlite_scan|httpfs|glob|getenv"
    r")\b",
    re.IGNORECASE,
)

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SQLGuardError(ValueError):
    """Raised when submitted SQL is not an allowed read-only statement."""


def strip_sql_comments(sql: str) -> str:
    """Remove SQL comments so keyword checks cannot be evaded.

    Runs before every other check: ``--\\nDROP TABLE t`` is a DROP, and
    a guard that inspects the raw text would not see it.
    """
    without_block = _BLOCK_COMMENT.sub(" ", sql or "")
    return _LINE_COMMENT.sub(" ", without_block)


def validate_sql(sql: str) -> str:
    """Validate that ``sql`` is one read-only statement.

    Returns:
        The comment-stripped, trailing-semicolon-free statement.

    Raises:
        SQLGuardError: If the statement is empty, is not a read-only
            leading keyword, chains multiple statements, or references a
            denied function or keyword.
    """
    cleaned = strip_sql_comments(sql).strip()
    if not cleaned:
        raise SQLGuardError("Empty SQL statement.")

    cleaned = cleaned.rstrip(";").strip()
    if not cleaned:
        raise SQLGuardError("Empty SQL statement.")

    if ";" in cleaned:
        raise SQLGuardError("Multiple SQL statements are not allowed; submit one query.")

    leading = re.split(r"[\s(]+", cleaned.lower(), maxsplit=1)[0]
    if leading not in _ALLOWED_LEADING:
        raise SQLGuardError(
            f"Only read-only queries are allowed (got '{leading}'). "
            "Start with SELECT, WITH, DESCRIBE, or SUMMARIZE."
        )

    denied = _DENY_PATTERN.search(cleaned)
    if denied:
        raise SQLGuardError(
            f"'{denied.group(1)}' is not allowed. Query the tables that are already "
            "loaded; file and network access are disabled."
        )

    return cleaned


@dataclass
class QueryResult:
    """Outcome of a successful query."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    elapsed_ms: int = 0
    sql: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
            "sql": self.sql,
            "warnings": self.warnings,
        }


def _json_safe(value: Any) -> Any:
    """Coerce a DuckDB value into something JSON can serialize."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


class DuckDBQueryEngine:
    """Run guarded read-only SQL against a scoped set of Parquet tables."""

    def __init__(
        self,
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        threads: int = DEFAULT_THREADS,
        max_materialize_rows: int = DEFAULT_MAX_MATERIALIZE_ROWS,
        max_payload_chars: int = DEFAULT_MAX_PAYLOAD_CHARS,
    ) -> None:
        self.max_rows = max(1, int(max_rows))
        self.timeout_seconds = float(timeout_seconds)
        self.memory_limit = memory_limit
        self.threads = max(1, int(threads))
        self.max_materialize_rows = int(max_materialize_rows)
        self.max_payload_chars = int(max_payload_chars)

    def _prepare(self, conn: Any, tables: dict[str, str]) -> list[str]:
        """Load the in-scope tables, then lock the connection down."""
        warnings: list[str] = []
        conn.execute(f"SET memory_limit='{self.memory_limit}'")
        conn.execute(f"SET threads={self.threads}")

        allowed_dirs: set[str] = set()
        for alias, parquet_path in tables.items():
            if not _IDENTIFIER_RE.match(alias):
                raise SQLGuardError(f"Invalid table alias: {alias!r}")
            path = Path(parquet_path)
            if not path.exists():
                warnings.append(f'table "{alias}" is missing its data file and was skipped')
                continue
            posix = path.as_posix().replace("'", "''")
            row_count = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{posix}')").fetchone()[0]
            if row_count > self.max_materialize_rows:
                # Too big to copy into memory; keep it as a view. The
                # view reads the file at query time, so its directory
                # goes on the allowlist below.
                conn.execute(f"CREATE VIEW \"{alias}\" AS SELECT * FROM read_parquet('{posix}')")
                allowed_dirs.add(path.parent.as_posix())
                warnings.append(
                    f'table "{alias}" has {row_count:,} rows and is queried directly from disk'
                )
            else:
                conn.execute(f"CREATE TABLE \"{alias}\" AS SELECT * FROM read_parquet('{posix}')")

        if allowed_dirs:
            # Views need their Parquet files readable at query time, but
            # only those: allowlist the exact directories, then disable
            # external access for everything else.
            quoted = ", ".join(f"'{d.replace(chr(39), chr(39) * 2)}'" for d in sorted(allowed_dirs))
            conn.execute(f"SET allowed_directories=[{quoted}]")
        # After this the connection cannot touch the filesystem outside
        # the allowlist (usually empty) or the network at all, whatever
        # the query text says.
        conn.execute("SET enable_external_access=false")
        conn.execute("SET lock_configuration=true")
        return warnings

    def run(
        self,
        sql: str,
        *,
        tables: dict[str, str],
        max_rows: int | None = None,
    ) -> QueryResult:
        """Execute a validated query against ``tables``.

        Args:
            sql: The agent-supplied query.
            tables: Mapping of table alias to Parquet file path.
            max_rows: Optional per-call row cap, clamped to the engine's.

        Returns:
            A :class:`QueryResult`.

        Raises:
            SQLGuardError: If the SQL is rejected by the text guard.
            ImportError: If duckdb is not installed.
            RuntimeError: If DuckDB rejects or interrupts the query.
        """
        statement = validate_sql(sql)
        limit = min(self.max_rows, max(1, int(max_rows or self.max_rows)))

        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "SQL over tables requires duckdb. Install openbench[tabular]."
            ) from exc

        started = time.monotonic()
        conn = duckdb.connect(":memory:")
        watchdog: threading.Timer | None = None
        try:
            warnings = self._prepare(conn, tables)

            leading = statement.split(None, 1)[0].lower()
            if leading in ("describe", "summarize"):
                # Not wrappable in a subquery; slice in Python instead.
                wrapped = statement
                slice_in_python = True
            else:
                wrapped = f"SELECT * FROM ({statement}) AS _openbench_q LIMIT {limit + 1}"
                slice_in_python = False

            watchdog = threading.Timer(self.timeout_seconds, conn.interrupt)
            watchdog.daemon = True
            watchdog.start()

            try:
                cursor = conn.execute(wrapped)
                columns = [description[0] for description in cursor.description or []]
                fetched = cursor.fetchall()
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc
            finally:
                watchdog.cancel()
                watchdog = None

            truncated = len(fetched) > limit
            if truncated or slice_in_python:
                fetched = fetched[:limit]

            rows = [[_json_safe(value) for value in row] for row in fetched]
            rows, payload_truncated = self._cap_payload(rows)
            if payload_truncated:
                truncated = True
                warnings.append("result truncated to fit the response size limit")

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                sql=statement,
                warnings=warnings,
            )
        finally:
            if watchdog is not None:
                watchdog.cancel()
            conn.close()

    def _cap_payload(self, rows: list[list[Any]]) -> tuple[list[list[Any]], bool]:
        """Drop trailing rows until the serialized result fits the cap."""
        if not rows:
            return rows, False
        serialized = json.dumps(rows, default=str)
        if len(serialized) <= self.max_payload_chars:
            return rows, False
        kept = rows
        while kept and len(json.dumps(kept, default=str)) > self.max_payload_chars:
            kept = kept[: max(1, len(kept) // 2)]
            if len(kept) == 1:
                break
        return kept, True


__all__ = [
    "DEFAULT_MAX_ROWS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DuckDBQueryEngine",
    "QueryResult",
    "SQLGuardError",
    "strip_sql_comments",
    "validate_sql",
]
