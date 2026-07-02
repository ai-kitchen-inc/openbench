"""Tools for the dashboard-generator SDK skill.

This skill exposes a metadata-first dashboard workflow:

1. ``extract_metadata(path)`` reads only enough tabular context for planning.
2. ``aggregate_data(path, query)`` executes read-only SQL aggregations.
3. ``generate_dashboard(view_model)`` renders a declarative dashboard artifact.

Pandas/openpyxl and requests are imported lazily so loading the skill never
fails because optional extras are missing.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import logging
import math
import os
import re
import sqlite3
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "extract_metadata",
    "aggregate_data",
    "generate_dashboard",
    "EXTRACT_METADATA_SCHEMA",
    "AGGREGATE_DATA_SCHEMA",
    "GENERATE_DASHBOARD_SCHEMA",
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

_ADAPTERS_MODULE: Any | None = None
_DASHBOARD_ADAPTER: Any | None = None
_DASHBOARD_ADAPTER_FACTORY: Any | None = None


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies.

    Supported keys:
    - ``dashboard_adapter``: adapter instance, adapter class, or adapter name
      (``"default"``, ``"stitch"``, or ``"auto"``).
    - ``dashboard_adapter_factory``: callable receiving ``output_path`` and
      ``public_url`` and returning an object with ``render(view_model)``.
    """
    global _DASHBOARD_ADAPTER, _DASHBOARD_ADAPTER_FACTORY
    if "dashboard_adapter" in kwargs:
        _DASHBOARD_ADAPTER = kwargs["dashboard_adapter"]
    if "dashboard_adapter_factory" in kwargs:
        _DASHBOARD_ADAPTER_FACTORY = kwargs["dashboard_adapter_factory"]


def _load_adapters_module():
    global _ADAPTERS_MODULE
    if _ADAPTERS_MODULE is not None:
        return _ADAPTERS_MODULE

    module_name = "openbench_dashboard_generator_mcp_adapters"
    if module_name in sys.modules:
        _ADAPTERS_MODULE = sys.modules[module_name]
        return _ADAPTERS_MODULE

    adapters_py = Path(__file__).with_name("adapters.py")
    spec = importlib.util.spec_from_file_location(
        module_name,
        adapters_py,
        submodule_search_locations=[str(adapters_py.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load dashboard adapters from {adapters_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _ADAPTERS_MODULE = module
    return module


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
        return None, None, f"Unsupported dashboard source type: {p.suffix!r}"

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
    """Return compact metadata for a CSV/XLSX dashboard source."""
    p = Path(path)
    df, resolved_sheet, err = _read_dataframe(path, sheet=sheet)
    if err:
        return _error(path, err)

    assert df is not None
    sample_size = max(1, min(int(sample_rows or _SAMPLE_ROWS), 20))
    return {
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
                "Use LIMIT when returning chart/table rows that could be large.",
            ],
        },
    }


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
            queries.append((str(query.get("id") or dataset_id or "dataset_1"), sql))
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
                    queries.append((str(item.get("id") or fallback_id), sql))
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

    return {
        "source": str(p.resolve()),
        "sheet": _json_value(resolved_sheet),
        "dialect": "sqlite",
        "table": str(table_name),
        "datasets": datasets,
        "errors": errors,
    }


def _slug(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe[:48] or "dashboard"


def _unique_dashboard_filename(title: str, filename: str | None) -> str:
    raw = Path(filename).name if filename else f"{_slug(title)}.html"
    path = Path(raw)
    suffix = path.suffix if path.suffix.lower() in {".html", ".htm"} else ".html"
    return f"{path.stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _public_url(path: Path) -> str:
    base = os.environ.get("OPENBENCH_EXPORT_URL_BASE")
    if not base:
        return path.as_posix()
    return f"{base.rstrip('/')}/{path.name}"


def _write_dashboard_export(view_model: dict[str, Any], output_path: Path) -> dict[str, Any]:
    adapters = _load_adapters_module()
    adapter = adapters.create_dashboard_adapter(
        output_path=output_path,
        public_url=_public_url(output_path),
        adapter=_DASHBOARD_ADAPTER,
        adapter_factory=_DASHBOARD_ADAPTER_FACTORY,
    )
    rendered = adapter.render(view_model)
    if hasattr(rendered, "to_dict") and callable(rendered.to_dict):
        return rendered.to_dict()
    if isinstance(rendered, dict):
        return rendered
    raise TypeError("Dashboard adapter render() must return a dict or DashboardRenderResult")


def _push_to_render_queue(item: dict[str, Any]) -> None:
    try:
        from openbench.chat.render_queue import push as _push
    except Exception:
        return
    with contextlib.suppress(Exception):
        _push(item)


def generate_dashboard(
    view_model: dict[str, Any],
    filename: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Create a dashboard artifact from a declarative ViewModel."""
    if not isinstance(view_model, dict) or not view_model:
        return _error("dashboard", "`view_model` must be a non-empty object")

    title = str(view_model.get("title") or "OpenBench Dashboard")
    out_dir = Path(output_dir or os.environ.get("OPENBENCH_EXPORT_DIR") or "outputs").resolve()
    out_name = _unique_dashboard_filename(title, filename)
    out_path = out_dir / out_name
    written = _write_dashboard_export(view_model, out_path)
    url = _public_url(out_path)
    rendered_view_model = written.get("viewModel") or written.get("view_model") or view_model
    datasets = (
        rendered_view_model.get("datasets", {}) if isinstance(rendered_view_model, dict) else {}
    )
    kpis = rendered_view_model.get("kpis", []) if isinstance(rendered_view_model, dict) else []
    sections = (
        rendered_view_model.get("sections", []) if isinstance(rendered_view_model, dict) else []
    )
    item = {
        "type": "dashboard",
        "title": title,
        "description": str(view_model.get("description") or ""),
        "render_mode": str(written.get("render_mode") or "a2ui"),
        "renderMode": str(written.get("render_mode") or "a2ui"),
        "viewModel": rendered_view_model,
        "datasets": datasets,
        "kpis": kpis,
        "sections": sections,
        "name": out_path.name,
        "url": url,
        "dashboardUrl": url,
        "path": written["file_path"],
        "mimeType": "text/html",
        "size": written["size_bytes"],
        "summary": str(view_model.get("description") or ""),
        "sectionCount": len(sections) if isinstance(sections, list) else 0,
        "kpiCount": len(kpis) if isinstance(kpis, list) else 0,
        "adapter": written.get("adapter", {}),
        "stitch": written.get("stitch", {}),
    }
    logger.info(
        "[dashboard] artifact created render_mode=%s title=%s datasets=%d kpis=%d sections=%d",
        item.get("render_mode"),
        item.get("title"),
        len(item.get("datasets") or {}),
        len(item.get("kpis") or []),
        len(item.get("sections") or []),
    )
    _push_to_render_queue(item)
    return item


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
    "Inspect a CSV/XLSX file and return compact dashboard planning metadata: "
    "columns, dtypes, row counts, samples, numeric ranges, and role hints. "
    "Use this first for dashboard requests.",
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
    "table `data`, in a single call. Use this after extract_metadata. Pass ALL the "
    "aggregations you need at once as a list of queries — one batched call returns "
    "every dataset; do NOT call this tool once per metric.",
    {
        "path": {"type": "string"},
        "sheet": {"type": "string", "description": "Optional Excel sheet name"},
        "query": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "List of read-only SQLite SQL queries — one per chart/metric you need. "
                "Send them all in one call. Example: ["
                '"SELECT region, SUM(revenue) AS revenue FROM data GROUP BY region '
                'ORDER BY revenue DESC LIMIT 10", '
                '"SELECT product, COUNT(*) AS orders FROM data GROUP BY product"]'
            ),
        },
        "dataset_id": {"type": "string", "description": "Optional output dataset id"},
        "table_name": {
            "type": "string",
            "description": "Optional SQL table name, defaults to data",
        },
        "max_rows": {
            "type": "integer",
            "description": "Maximum rows returned per dataset, default 1000",
        },
    },
    ["path", "query"],
)

GENERATE_DASHBOARD_SCHEMA = _schema(
    "generate_dashboard",
    "Render a declarative dashboard ViewModel as an HTML artifact. The ViewModel "
    "must contain dashboard structure and aggregate datasets, not raw UI code.",
    {
        "view_model": {
            "type": "object",
            "description": "Dashboard ViewModel with title, datasets, kpis, and sections.",
        },
        "filename": {"type": "string", "description": "Optional .html filename"},
        "output_dir": {"type": "string", "description": "Optional output directory"},
    },
    ["view_model"],
)
