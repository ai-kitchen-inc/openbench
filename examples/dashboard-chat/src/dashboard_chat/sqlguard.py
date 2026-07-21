"""Read-only SQL execution guard for Dashboard Chat.

Every SQL statement that reaches a user's database goes through this
module — both the LLM's LIMIT-0 validation probes and the chart data
fetches. Only single SELECT (or WITH ... SELECT) statements survive;
row output is always capped; values are coerced to JSON-safe types.

Adapted from the db-server MCP guard
(``examples/general-chat/mcp/db-server/app/db.py``) for synchronous
SQLAlchemy engines and per-user use.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

DEFAULT_MAX_ROWS = 5000

_FORBIDDEN_PATTERNS = tuple(
    re.compile(rf"\b{keyword}\b")
    for keyword in (
        "DROP",
        "DELETE",
        "INSERT",
        "UPDATE",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "REPLACE",
        "MERGE",
        "EXEC",
        "EXECUTE",
        "CALL",
        "ATTACH",
        "DETACH",
        "PRAGMA",
        "GRANT",
        "REVOKE",
        "VACUUM",
        "INTO",
    )
)

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)


@dataclass
class QueryResult:
    """JSON-ready result of a guarded SELECT."""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "truncated": self.truncated,
            "elapsedMs": self.elapsed_ms,
        }


def max_rows() -> int:
    try:
        return max(1, int(os.getenv("DASHBOARD_CHAT_MAX_ROWS", str(DEFAULT_MAX_ROWS))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ROWS


def _strip_comments(sql: str) -> str:
    without_line = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", without_line, flags=re.DOTALL)


def is_select_only(sql: str) -> bool:
    """True when ``sql`` is a single read-only SELECT/WITH statement."""
    cleaned = _strip_comments(sql or "")
    normalized = " ".join(cleaned.split()).upper()
    if not normalized:
        return False
    if not re.match(r"^(SELECT|WITH)\b", normalized):
        return False
    # One statement only: any ';' followed by more SQL is rejected.
    if re.search(r";\s*\S", normalized):
        return False
    return not any(pattern.search(normalized) for pattern in _FORBIDDEN_PATTERNS)


def apply_limit(sql: str, limit: int) -> str:
    """Cap the statement's LIMIT at ``limit`` (replace larger, append missing)."""
    stripped = sql.strip().rstrip(";")
    match = _LIMIT_RE.search(stripped)
    if match:
        existing = int(match.group(1))
        if existing <= limit:
            return stripped
        return _LIMIT_RE.sub(f"LIMIT {limit}", stripped, count=1)
    return f"{stripped} LIMIT {limit}"


def _coerce(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _apply_statement_timeout(connection: Any, dialect: str, seconds: int) -> None:
    """Best-effort per-statement timeout; unsupported dialects degrade to LIMIT-only."""
    try:
        if dialect == "postgresql":
            connection.execute(text(f"SET LOCAL statement_timeout = {seconds * 1000}"))
        elif dialect == "mysql":
            connection.execute(text(f"SET SESSION max_execution_time = {seconds * 1000}"))
    except Exception:
        pass


def execute_select(engine: Engine, sql: str, *, limit: int | None = None) -> QueryResult:
    """Execute a guarded SELECT and return JSON-ready columns/rows.

    Raises:
        ValueError: If the statement is not a single read-only SELECT.
    """
    if not is_select_only(sql):
        raise ValueError("Only single read-only SELECT statements are allowed.")
    cap = min(limit, max_rows()) if limit is not None else max_rows()
    bounded = apply_limit(sql, cap)
    started = time.perf_counter()
    with engine.connect() as connection:
        _apply_statement_timeout(connection, engine.dialect.name, seconds=20)
        cursor = connection.execute(text(bounded))
        columns = list(cursor.keys())
        raw_rows = cursor.fetchall()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    rows = [[_coerce(value) for value in row] for row in raw_rows]
    return QueryResult(
        columns=columns,
        rows=rows,
        truncated=len(rows) >= cap > 0,
        elapsed_ms=elapsed_ms,
    )


def validate_select(engine: Engine, sql: str) -> dict:
    """Validate a SELECT without exposing data: LIMIT 0 returns columns only.

    This is the only database feedback the LLM ever receives — zero rows
    by construction, plus the driver's error message on failure.
    """
    if not is_select_only(sql or ""):
        return {
            "ok": False,
            "error": "Only a single read-only SELECT (or WITH ... SELECT) statement is allowed.",
        }
    try:
        result = execute_select(engine, sql, limit=0)
    except Exception as exc:  # Driver errors are the useful feedback here.
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "columns": result.columns}
