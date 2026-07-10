"""General-purpose tabular metadata and aggregation tools.

The aggregate MCP is intentionally dashboard-neutral. It can inspect CSV/XLSX
files and run read-only SQLite queries for ordinary table answers, while also
persisting aggregate datasets to the dashboard state file so the dashboard MCP
can render those datasets later in a multi-server workflow.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "extract_metadata",
    "aggregate_data",
    "EXTRACT_METADATA_SCHEMA",
    "AGGREGATE_DATA_SCHEMA",
]

_SAMPLE_ROWS = 5
_MAX_DISTINCT_SAMPLE = 12
_SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
_DEFAULT_SQL_TABLE = "data"
_DEFAULT_SQL_MAX_ROWS = 1000
_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_SQL_KEYWORDS = {
    "ALTER",
    "ATTACH",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "INSERT",
    "PRAGMA",
    "REINDEX",
    "REPLACE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}

_LAST_AGGREGATE_DATASETS: dict[str, list[dict[str, Any]]] = {}
_LAST_SOURCE_CONTEXT: dict[str, Any] = {}


def _dashboard_state_path() -> Path:
    raw = (
        os.environ.get("OPENBENCH_DASHBOARD_STATE_PATH")
        or os.environ.get("GENERAL_CHAT_DASHBOARD_STATE_PATH")
    )
    return (
        Path(raw).expanduser().resolve()
        if raw
        else Path(".openbench/dashboard_generator_state.json").resolve()
    )


def _load_dashboard_state() -> dict[str, Any]:
    path = _dashboard_state_path()
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def _save_dashboard_state(state: dict[str, Any]) -> None:
    path = _dashboard_state_path()
    with contextlib.suppress(Exception):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_value(state), ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _persist_source_context(context: dict[str, Any]) -> None:
    _LAST_SOURCE_CONTEXT.clear()
    _LAST_SOURCE_CONTEXT.update(context)
    state = _load_dashboard_state()
    state["source_context"] = context
    aggregate_datasets = state.get("aggregate_datasets")
    state["aggregate_datasets"] = aggregate_datasets if isinstance(aggregate_datasets, dict) else {}
    _save_dashboard_state(state)


def _persist_aggregate_datasets() -> None:
    state = _load_dashboard_state()
    source_context = state.get("source_context")
    if _LAST_SOURCE_CONTEXT:
        state["source_context"] = _LAST_SOURCE_CONTEXT
    elif isinstance(source_context, dict):
        state["source_context"] = source_context
    state["aggregate_datasets"] = {
        dataset_id: records
        for dataset_id, records in _LAST_AGGREGATE_DATASETS.items()
        if isinstance(records, list)
    }
    _save_dashboard_state(state)


def _remember_aggregate_datasets(datasets: list[dict[str, Any]]) -> None:
    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        dataset_id = dataset.get("id") or dataset.get("name")
        records = dataset.get("records")
        if dataset_id and isinstance(records, list):
            _LAST_AGGREGATE_DATASETS[str(dataset_id)] = [
                row for row in records if isinstance(row, dict)
            ]
    _persist_aggregate_datasets()


def _error(source: str, message: str) -> dict[str, Any]:
    return {"error": message, "source": source}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _load_pandas():
    try:
        import pandas as pd
    except ImportError:
        return None
    return pd


def _read_dataframe(path: str, sheet: str | int | None = None):
    pd = _load_pandas()
    if pd is None:
        return None, None, "pandas is required - install openbench[data]"

    p = Path(path)
    if not p.exists():
        return None, None, f"File not found: {path}"
    if p.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        return None, None, f"Unsupported aggregate source type: {p.suffix!r}"

    try:
        if p.suffix.lower() == ".csv":
            df = pd.read_csv(p, encoding="utf-8-sig")
            return df, None, None
        workbook = pd.ExcelFile(p)
        resolved_sheet = sheet if sheet is not None else workbook.sheet_names[0]
        df = pd.read_excel(p, sheet_name=resolved_sheet)
        return df, resolved_sheet, None
    except ImportError as exc:
        return None, None, f"Excel reader missing: {exc} - install openbench[data]"
    except Exception as exc:
        return None, None, f"Failed to read tabular file: {exc}"


def _sheet_names(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        return []
    pd = _load_pandas()
    if pd is None:
        return []
    try:
        return list(pd.ExcelFile(path).sheet_names)
    except Exception:
        return []


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        with contextlib.suppress(Exception):
            return _json_value(value.item())
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    try:
        pd = _load_pandas()
        if pd is not None and pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _records(df: Any, limit: int | None = None) -> list[dict[str, Any]]:
    selected = df if limit is None else df.head(limit)
    raw = selected.to_dict(orient="records")
    return [_json_value(row) for row in raw]


def _column_profile(df: Any, column: str) -> dict[str, Any]:
    pd = _load_pandas()
    series = df[column]
    non_null = series.dropna()
    profile: dict[str, Any] = {
        "name": str(column),
        "dtype": str(series.dtype),
        "null_count": int(series.isna().sum()),
        "non_null_count": int(non_null.size),
        "unique_count": int(non_null.nunique(dropna=True)),
        "sample_values": [_json_value(v) for v in non_null.head(_MAX_DISTINCT_SAMPLE).tolist()],
    }
    if pd is not None and pd.api.types.is_numeric_dtype(series):
        profile["role_hint"] = "metric"
        if not non_null.empty:
            profile["min"] = _json_value(non_null.min())
            profile["max"] = _json_value(non_null.max())
            profile["mean"] = _json_value(non_null.mean())
            profile["median"] = _json_value(non_null.median())
    elif pd is not None and pd.api.types.is_datetime64_any_dtype(series):
        profile["role_hint"] = "time"
        if not non_null.empty:
            profile["min"] = _json_value(non_null.min())
            profile["max"] = _json_value(non_null.max())
    else:
        ratio = (profile["unique_count"] / max(int(len(df)), 1)) if len(df) else 0
        profile["role_hint"] = "category" if ratio <= 0.35 else "label"
    return profile


def extract_metadata(path: str, sheet: str | int | None = None, sample_rows: int = _SAMPLE_ROWS) -> dict[str, Any]:
    """Return compact metadata for a CSV/XLSX source before aggregation."""
    p = Path(path)
    df, resolved_sheet, err = _read_dataframe(path, sheet=sheet)
    if err:
        return _error(path, err)

    assert df is not None
    sample_size = max(1, min(int(sample_rows or _SAMPLE_ROWS), 20))
    result = {
        "source": str(p.resolve()),
        "file_name": p.name,
        "file_hash": _file_hash(p),
        "format": p.suffix.lower().lstrip("."),
        "sheet": _json_value(resolved_sheet),
        "sheets": _sheet_names(p),
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [_column_profile(df, column) for column in df.columns],
        "sample": _records(df, sample_size),
        "sql": {
            "dialect": "sqlite",
            "table": _DEFAULT_SQL_TABLE,
            "identifier_quote": '"',
            "column_names": [str(column) for column in df.columns],
            "notes": [
                "Write read-only SELECT or WITH queries only.",
                f"Use `{_DEFAULT_SQL_TABLE}` as the source table name.",
                "Quote column names with double quotes when they contain spaces or punctuation.",
                "Use LIMIT when returning table rows that could be large.",
            ],
        },
    }
    _persist_source_context({"path": str(p.resolve()), "sheet": _json_value(resolved_sheet)})
    return result


def _normalise_sql_queries(
    query: str | dict[str, Any] | list[Any],
    dataset_id: str | None,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    queries: list[tuple[str, str]] = []
    errors: list[dict[str, Any]] = []

    if isinstance(query, str):
        return [(dataset_id or "dataset_1", query)], errors

    if isinstance(query, dict):
        if "queries" in query:
            return _normalise_sql_queries(query["queries"], dataset_id)
        sql = query.get("query") or query.get("sql")
        if isinstance(sql, str):
            op_id = query.get("id") or query.get("name") or dataset_id or "dataset_1"
            queries.append((str(op_id), sql))
        else:
            errors.append({"error": "query object must include a SQL string in `query` or `sql`"})
        return queries, errors

    if isinstance(query, list):
        for index, item in enumerate(query, start=1):
            fallback_id = f"dataset_{index}"
            if isinstance(item, str):
                queries.append((fallback_id, item))
                continue
            if isinstance(item, dict):
                sql = item.get("query") or item.get("sql")
                if isinstance(sql, str):
                    op_id = item.get("id") or item.get("name") or fallback_id
                    queries.append((str(op_id), sql))
                else:
                    errors.append(
                        {
                            "index": index,
                            "error": "query object must include a SQL string in `query` or `sql`",
                        }
                    )
                continue
            errors.append({"index": index, "error": "query item must be a string or object"})
        return queries, errors

    errors.append({"error": "`query` must be a SQL string, object, or list"})
    return queries, errors


def _validate_readonly_sql(sql: str) -> tuple[str | None, str | None]:
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if not cleaned:
        return None, "SQL query cannot be empty"
    if ";" in cleaned:
        return None, "Only one SQL statement is allowed"

    match = re.match(r"^\s*([A-Za-z]+)\b", cleaned)
    first_keyword = match.group(1).upper() if match else ""
    if first_keyword not in {"SELECT", "WITH"}:
        return None, "Only read-only SELECT or WITH queries are allowed"

    upper_sql = cleaned.upper()
    for keyword in sorted(_FORBIDDEN_SQL_KEYWORDS):
        if re.search(rf"\b{keyword}\b", upper_sql):
            return None, f"Forbidden SQL keyword: {keyword}"

    return cleaned, None


def aggregate_data(
    path: str,
    query: str | dict[str, Any] | list[Any],
    sheet: str | int | None = None,
    table_name: str = _DEFAULT_SQL_TABLE,
    dataset_id: str | None = None,
    max_rows: int = _DEFAULT_SQL_MAX_ROWS,
) -> dict[str, Any]:
    """Execute read-only SQL aggregation queries against a CSV/XLSX file."""
    p = Path(path)
    df, resolved_sheet, err = _read_dataframe(path, sheet=sheet)
    if err:
        return _error(path, err)

    if not _SQL_IDENTIFIER_RE.match(str(table_name)):
        return _error(path, "`table_name` must be a simple SQL identifier")

    try:
        row_limit = max(1, min(int(max_rows), 10000))
    except Exception:
        row_limit = _DEFAULT_SQL_MAX_ROWS

    assert df is not None
    pd = _load_pandas()
    assert pd is not None
    datasets: list[dict[str, Any]] = []
    queries, errors = _normalise_sql_queries(query, dataset_id)
    if not queries and not errors:
        errors.append({"error": "`query` must include at least one SQL statement"})

    try:
        with sqlite3.connect(":memory:") as conn:
            df.to_sql(str(table_name), conn, index=False, if_exists="replace")
            for op_id, sql in queries:
                cleaned_sql, validation_error = _validate_readonly_sql(sql)
                if validation_error:
                    errors.append({"id": op_id, "error": validation_error, "query": sql})
                    continue
                assert cleaned_sql is not None
                try:
                    result_df = pd.read_sql_query(cleaned_sql, conn)
                    records = _records(result_df, row_limit)
                    datasets.append(
                        {
                            "id": op_id,
                            "records": records,
                            "row_count": len(records),
                            "total_row_count": int(len(result_df)),
                            "truncated": int(len(result_df)) > len(records),
                            "query": cleaned_sql,
                        }
                    )
                except Exception as exc:
                    errors.append({"id": op_id, "error": str(exc), "query": cleaned_sql})
    except Exception as exc:
        errors.append({"error": f"Failed to prepare SQL workspace: {exc}"})

    result = {
        "source": str(p.resolve()),
        "sheet": _json_value(resolved_sheet),
        "dialect": "sqlite",
        "table": str(table_name),
        "datasets": datasets,
        "errors": errors,
    }
    _persist_source_context({"path": str(p.resolve()), "sheet": _json_value(resolved_sheet)})
    _remember_aggregate_datasets(datasets)
    return result


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
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


EXTRACT_METADATA_SCHEMA = _schema(
    "extract_metadata",
    "Inspect a CSV/XLSX file for general aggregation: columns, dtypes, row counts, "
    "samples, numeric ranges, and SQLite query hints. Use this before aggregate_data "
    "when the needed column names are not already known.",
    {
        "path": {"type": "string", "description": "CSV/XLSX file path"},
        "sheet": {"type": "string", "description": "Optional Excel sheet name"},
        "sample_rows": {"type": "integer", "description": "Sample row count, default 5"},
    },
    ["path"],
)

AGGREGATE_DATA_SCHEMA = _schema(
    "aggregate_data",
    "Run read-only SQLite SELECT/WITH queries against a CSV/XLSX file loaded as "
    "table `data`. Use this for general tabular aggregation and table answers, "
    "not only dashboards. Pass related aggregations together as a list.",
    {
        "path": {"type": "string", "description": "CSV/XLSX file path"},
        "sheet": {"type": "string", "description": "Optional Excel sheet name"},
        "query": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Read-only SQLite SQL query or list of queries. Query objects may "
                "use `id`/`name` plus `sql`/`query` to name result datasets."
            ),
        },
        "table_name": {
            "type": "string",
            "description": "SQLite table name for the loaded file, default `data`.",
        },
        "dataset_id": {
            "type": "string",
            "description": "Optional dataset id for a single SQL query.",
        },
        "max_rows": {
            "type": "integer",
            "description": "Maximum rows returned per dataset, capped at 10000.",
        },
    },
    ["path", "query"],
)
