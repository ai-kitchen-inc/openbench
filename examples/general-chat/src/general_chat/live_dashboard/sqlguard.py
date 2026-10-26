"""Read-only SQL guard for live dashboard queries.

Every query stored on a live dashboard is re-run unattended by the scheduler,
so it is validated once at save time: a single ``SELECT`` / ``WITH ... SELECT``
statement, no statement separators, no DDL/DML keywords. The ``db_server`` MCP
applies its own SELECT-only check and row cap on execution; this guard keeps
bad statements out of the store so they never reach the schedule.

Mirrors ``examples/dashboard-chat/src/dashboard_chat/sqlguard.py`` (examples
cannot import each other).
"""

from __future__ import annotations

import re

MAX_SQL_CHARS = 20_000

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
        # Side-effect / exfiltration functions reachable from a SELECT.
        "PG_SLEEP",
        "PG_TERMINATE_BACKEND",
        "PG_CANCEL_BACKEND",
        "PG_READ_FILE",
        "PG_READ_BINARY_FILE",
        "PG_LS_DIR",
        "LO_IMPORT",
        "LO_EXPORT",
        "SET_CONFIG",
        "DBLINK",
        "COPY",
        "LOAD_EXTENSION",
    )
)

_DATASET_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def strip_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* */`` block comments."""
    without_line = re.sub(r"--.*$", "", sql or "", flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", without_line, flags=re.DOTALL)


def is_select_only(sql: str) -> bool:
    """True when ``sql`` is one read-only SELECT/WITH statement.

    The separator and keyword checks run on the RAW text: stripping comments
    first would let ``SELECT '--'; INSERT ...`` hide its second statement
    behind a string literal. Only the leading-keyword check uses the
    comment-stripped form so a header comment stays allowed. Keywords inside
    string literals are rejected too (false positives beat a bypass).
    """
    raw = (sql or "").strip()
    if not raw or len(raw) > MAX_SQL_CHARS:
        return False
    raw_upper = raw.upper()
    # One statement only: any ';' that is not the trailing terminator.
    if ";" in raw_upper.rstrip(";"):
        return False
    if any(pattern.search(raw_upper) for pattern in _FORBIDDEN_PATTERNS):
        return False
    normalized = " ".join(strip_comments(raw).split()).upper()
    return bool(re.match(r"^(SELECT|WITH)\b", normalized))


def is_valid_dataset_key(key: str) -> bool:
    """Dataset keys are JSON-object keys the LLM references from panels."""
    return bool(isinstance(key, str) and _DATASET_KEY_RE.match(key))
