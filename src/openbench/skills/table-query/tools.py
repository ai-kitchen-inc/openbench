"""Tools for the table-query SDK skill.

The table catalog and the current turn's scope are injected by the host
application via :func:`bind`. Table aliases are resolved through the
catalog and intersected with the bound scope, so the model can only reach
Parquet files belonging to sources it was shown.

``duckdb`` is imported lazily inside the query engine, so loading this
skill never requires the ``tabular`` extra at install time — the failure
surfaces only when a query is actually run.

Every tool returns a plain dict and never raises. A rejected or failing
query comes back as ``{"error": ..., "available_columns": ...}`` so the
agent can fix it and retry within the same turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "DESCRIBE_SOURCE_TABLE_SCHEMA",
    "LIST_SOURCE_TABLES_SCHEMA",
    "QUERY_SOURCE_TABLE_SCHEMA",
    "bind",
    "describe_source_table",
    "list_source_tables",
    "query_source_table",
]

DEFAULT_QUERY_ROWS = 200


# ---------------------------------------------------------------------------
# Bound dependencies (populated by skill.bind() at agent build)
# ---------------------------------------------------------------------------

_table_catalog: Any | None = None
_table_scope_provider: Callable[[], Any] | None = None
_max_rows: int | None = None
_timeout_seconds: float | None = None


def bind(
    table_catalog: Any = None,
    source_scope_provider: Callable[[], Any] | None = None,
    duckdb_max_rows: int | None = None,
    duckdb_timeout_s: float | None = None,
    **_: object,
) -> None:
    """Inject the table catalog, scope accessor, and query limits.

    Called by :meth:`SkillRegistry.bind` during :class:`BaseAgent`
    construction. Extra kwargs are ignored so other bindings can layer on.

    Args:
        table_catalog: A ``TableCatalog``-shaped object exposing
            ``list_for`` and ``get_by_name``.
        source_scope_provider: Zero-argument callable returning the current
            turn's scope, with ``source_ids`` and ``owner`` attributes.
            Shared with the source-retrieval skill so both agree on what
            the turn may read.
        duckdb_max_rows: Optional row cap override.
        duckdb_timeout_s: Optional query timeout override, in seconds.
    """
    global _table_catalog, _table_scope_provider, _max_rows, _timeout_seconds
    _table_catalog = table_catalog
    _table_scope_provider = source_scope_provider
    _max_rows = duckdb_max_rows
    _timeout_seconds = duckdb_timeout_s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}


def _scope() -> Any | None:
    if _table_scope_provider is None:
        return None
    try:
        return _table_scope_provider()
    except Exception:
        return None


def _scoped_artifacts(source_id: str | None = None) -> list[Any]:
    """Every table the current turn may query, optionally one source's."""
    if _table_catalog is None:
        return []
    scope = _scope()
    source_ids = [str(value) for value in (getattr(scope, "source_ids", None) or [])]
    if source_id:
        if source_ids and source_id not in source_ids:
            return []
        source_ids = [source_id]
    if not source_ids:
        return []
    try:
        return list(_table_catalog.list_for(source_ids=source_ids))
    except Exception:
        return []


def _column_map(artifacts: list[Any]) -> dict[str, list[str]]:
    return {artifact.name: [column.name for column in artifact.columns] for artifact in artifacts}


def _engine() -> Any:
    from openbench.data.tabular.query import DuckDBQueryEngine

    kwargs: dict[str, Any] = {}
    if _max_rows:
        kwargs["max_rows"] = int(_max_rows)
    if _timeout_seconds:
        kwargs["timeout_seconds"] = float(_timeout_seconds)
    return DuckDBQueryEngine(**kwargs)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def list_source_tables(source_id: str | None = None) -> dict[str, Any]:
    """List the queryable tables in this conversation.

    Args:
        source_id: Restrict to one source's tables. Omit for all.

    Returns:
        ``{"tables": [...], "count"}`` or ``{"error": ...}``.
    """
    if _table_catalog is None:
        return _error("Table queries are not available in this deployment.")

    artifacts = _scoped_artifacts(source_id)
    if not artifacts:
        return {
            "tables": [],
            "count": 0,
            "note": "No data tables are available in this conversation.",
        }

    return {
        "tables": [
            {
                "table": artifact.name,
                "display_name": artifact.display_name,
                "source_id": artifact.source_id,
                "row_count": artifact.row_count,
                "column_count": len(artifact.columns),
            }
            for artifact in artifacts
        ],
        "count": len(artifacts),
    }


def describe_source_table(table: str) -> dict[str, Any]:
    """Show a table's columns, types, and sample rows.

    Args:
        table: Table name from a source card or ``list_source_tables``.

    Returns:
        ``{"table", "row_count", "columns", "sample_rows"}`` or
        ``{"error": ...}``.
    """
    if _table_catalog is None:
        return _error("Table queries are not available in this deployment.")
    if not (table or "").strip():
        return _error("Provide a table name.")

    artifacts = _scoped_artifacts()
    match = next((artifact for artifact in artifacts if artifact.name == table), None)
    if match is None:
        return _error(
            f"Unknown table '{table}'.",
            available_tables=[artifact.name for artifact in artifacts],
        )

    return {
        "table": match.name,
        "display_name": match.display_name,
        "source_id": match.source_id,
        "row_count": match.row_count,
        "columns": [
            {
                "name": column.name,
                "dtype": column.dtype,
                "null_count": column.null_count,
                "distinct_estimate": column.distinct_estimate,
                "min": column.min,
                "max": column.max,
                "sample_values": column.sample_values,
            }
            for column in match.columns
        ],
        "sample_rows": match.sample_rows,
    }


def query_source_table(
    sql: str,
    tables: list[str] | None = None,
    max_rows: int = DEFAULT_QUERY_ROWS,
) -> dict[str, Any]:
    """Run read-only SQL over the uploaded data tables.

    Args:
        sql: One read-only statement (SELECT, WITH, DESCRIBE, SUMMARIZE).
        tables: Tables to load. Omit to load every table in scope.
        max_rows: Maximum rows to return.

    Returns:
        ``{"columns", "rows", "row_count", "truncated", "elapsed_ms", "sql"}``
        or ``{"error", "sql", "available_columns", "hint"}``.
    """
    if _table_catalog is None:
        return _error("Table queries are not available in this deployment.")
    if not (sql or "").strip():
        return _error("Provide a SQL query.")

    artifacts = _scoped_artifacts()
    if not artifacts:
        return _error("No data tables are available in this conversation.")

    if tables:
        wanted = {str(name) for name in tables}
        known = {artifact.name for artifact in artifacts}
        unknown = sorted(wanted - known)
        if unknown:
            return _error(
                f"Unknown table(s): {', '.join(unknown)}.",
                available_tables=sorted(known),
            )
        artifacts = [artifact for artifact in artifacts if artifact.name in wanted]

    table_paths = {artifact.name: artifact.parquet_path for artifact in artifacts}
    columns = _column_map(artifacts)

    try:
        from openbench.data.tabular.query import SQLGuardError

        result = _engine().run(sql, tables=table_paths, max_rows=max_rows)
    except ImportError as exc:
        return _error(str(exc))
    except SQLGuardError as exc:
        return _error(
            str(exc),
            sql=sql,
            available_columns=columns,
            hint=(
                "Only one read-only statement is allowed: SELECT, WITH, DESCRIBE, "
                "or SUMMARIZE. File and network access are disabled."
            ),
        )
    except Exception as exc:
        return _error(
            f"Query failed: {exc}",
            sql=sql,
            available_columns=columns,
            hint=(
                "Check the table and column names against available_columns. "
                "Quote identifiers with double quotes and string literals with "
                "single quotes."
            ),
        )

    return result.to_dict()


#: DuckDB gets its own wall-clock stop; this is the ToolExecutor's outer
#: bound so a hung query cannot hold the reasoning loop open.
query_source_table.timeout_seconds = 25.0


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


LIST_SOURCE_TABLES_SCHEMA = _schema(
    "list_source_tables",
    "List the data tables available in this conversation, with their row and column counts.",
    {
        "source_id": {
            "type": "string",
            "description": "Restrict to one source's tables. Omit for all tables.",
        },
    },
    [],
)

DESCRIBE_SOURCE_TABLE_SCHEMA = _schema(
    "describe_source_table",
    "Show a table's columns, types, value ranges, and sample rows. Call this "
    "when a column name or meaning is unclear before querying.",
    {
        "table": {
            "type": "string",
            "description": "Table name from a source card or list_source_tables.",
        },
    },
    ["table"],
)

QUERY_SOURCE_TABLE_SCHEMA = _schema(
    "query_source_table",
    "Run read-only SQL over the user's uploaded spreadsheets and CSVs. Use "
    "this for every number the user asks for - totals, counts, averages, "
    "rankings, breakdowns - rather than estimating from sample rows.",
    {
        "sql": {
            "type": "string",
            "description": (
                "One read-only DuckDB statement (SELECT, WITH, DESCRIBE, or "
                "SUMMARIZE). Aggregate in SQL rather than selecting every row."
            ),
        },
        "tables": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Tables to load for this query. Omit to load every table in this conversation."
            ),
        },
        "max_rows": {
            "type": "integer",
            "description": "Maximum rows to return. Default 200.",
        },
    },
    ["sql"],
)
