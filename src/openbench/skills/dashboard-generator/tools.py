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
import json
import logging
import math
import os
import re
import sqlite3
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "extract_metadata",
    "aggregate_data",
    "generate_dashboard",
    "load_dashboard_memory",
    "EXTRACT_METADATA_SCHEMA",
    "AGGREGATE_DATA_SCHEMA",
    "GENERATE_DASHBOARD_SCHEMA",
    "LOAD_DASHBOARD_MEMORY_SCHEMA",
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
_DASHBOARD_MEMORY_DB_PATH: str | None = None
_LAST_AGGREGATE_DATASETS: dict[str, list[dict[str, Any]]] = {}
_LAST_SOURCE_SIGNATURES: dict[str, str] = {}
_LAST_SOURCE_LABELS: dict[str, str] = {}
_LAST_SOURCE_CONTEXT: dict[str, Any] = {}


def _dashboard_state_path() -> Path:
    raw = (
        os.environ.get("OPENBENCH_DASHBOARD_STATE_PATH")
        or os.environ.get("GENERAL_CHAT_DASHBOARD_STATE_PATH")
    )
    if raw:
        return Path(raw).expanduser().resolve()
    memory_db = os.environ.get("OPENBENCH_DASHBOARD_MEMORY_DB") or _DASHBOARD_MEMORY_DB_PATH
    if memory_db:
        return Path(memory_db).expanduser().resolve().with_name("dashboard_generator_state.json")
    return Path(".openbench/dashboard_generator_state.json").resolve()


def _load_dashboard_state() -> dict[str, Any]:
    path = _dashboard_state_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def _save_dashboard_state(state: dict[str, Any]) -> None:
    path = _dashboard_state_path()
    with contextlib.suppress(Exception):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(_json_value(state), handle, ensure_ascii=False, sort_keys=True)


def _restore_dashboard_state() -> None:
    state = _load_dashboard_state()
    source_context = state.get("source_context")
    if isinstance(source_context, dict) and source_context.get("path"):
        _LAST_SOURCE_CONTEXT.update(source_context)
    aggregate_datasets = state.get("aggregate_datasets")
    if isinstance(aggregate_datasets, dict):
        for dataset_id, records in aggregate_datasets.items():
            if isinstance(records, list):
                _LAST_AGGREGATE_DATASETS[str(dataset_id)] = [
                    row for row in records if isinstance(row, dict)
                ]


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


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies.

    Supported keys:
    - ``dashboard_adapter``: adapter instance, adapter class, or adapter name
      (``"default"``, ``"stitch"``, or ``"auto"``).
    - ``dashboard_adapter_factory``: callable receiving ``output_path`` and
      ``public_url`` and returning an object with ``render(view_model)``.
    - ``dashboard_memory_db_path``: SQLite file used for persisted dashboard
      ViewModels shared by SDK and MCP tool calls.
    """
    global _DASHBOARD_ADAPTER, _DASHBOARD_ADAPTER_FACTORY, _DASHBOARD_MEMORY_DB_PATH
    if "dashboard_adapter" in kwargs:
        _DASHBOARD_ADAPTER = kwargs["dashboard_adapter"]
    if "dashboard_adapter_factory" in kwargs:
        _DASHBOARD_ADAPTER_FACTORY = kwargs["dashboard_adapter_factory"]
    if "dashboard_memory_db_path" in kwargs:
        value = kwargs["dashboard_memory_db_path"]
        _DASHBOARD_MEMORY_DB_PATH = str(value) if value else None


def _load_adapters_module():
    global _ADAPTERS_MODULE
    if _ADAPTERS_MODULE is not None:
        return _ADAPTERS_MODULE

    module_name = "openbench_skill_dashboard_generator_adapters"
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


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True)


def _dashboard_memory_db_path() -> Path:
    raw = (
        _DASHBOARD_MEMORY_DB_PATH
        or os.environ.get("OPENBENCH_DASHBOARD_MEMORY_DB")
        or os.environ.get("GENERAL_CHAT_DASHBOARD_MEMORY_DB")
        or ".openbench/dashboard_memory.db"
    )
    return Path(raw).expanduser().resolve()


def _dashboard_memory_enabled() -> bool:
    raw = os.environ.get("OPENBENCH_DASHBOARD_MEMORY_ENABLED", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _connect_dashboard_memory() -> sqlite3.Connection | None:
    if not _dashboard_memory_enabled():
        return None
    path = _dashboard_memory_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            title TEXT NOT NULL,
            source_signature TEXT,
            source_label TEXT,
            source_path TEXT,
            sheet TEXT,
            dashboard_key TEXT,
            view_model TEXT NOT NULL,
            artifact TEXT NOT NULL,
            revision_of TEXT,
            revision_notes TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_source_signature "
        "ON dashboards(source_signature, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_key ON dashboards(dashboard_key, updated_at)"
    )
    conn.commit()
    return conn


def _dashboard_id(view_model: dict[str, Any], source_signature: str | None = None) -> str:
    title = str(view_model.get("title") or "dashboard")
    seed = _json_dumps(
        {
            "title": title,
            "source_signature": source_signature,
            "view_model": view_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return f"dash-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _source_signature_from_metadata(metadata: dict[str, Any]) -> str:
    columns = []
    for column in metadata.get("columns") or []:
        if not isinstance(column, dict):
            continue
        columns.append(
            {
                "name": str(column.get("name") or ""),
                "dtype": str(column.get("dtype") or ""),
                "role_hint": str(column.get("role_hint") or ""),
            }
        )
    payload = {
        "format": str(metadata.get("format") or ""),
        "sheet": _json_value(metadata.get("sheet")),
        "columns": columns,
    }
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()[:24]


def _source_signature_for_path(path: str, sheet: str | int | None = None) -> str | None:
    key = str(Path(path).resolve())
    if sheet is not None:
        key = f"{key}::{sheet}"
    if key in _LAST_SOURCE_SIGNATURES:
        return _LAST_SOURCE_SIGNATURES[key]
    metadata = extract_metadata(path, sheet=sheet, sample_rows=1)
    if isinstance(metadata, dict) and not metadata.get("error"):
        return str(metadata.get("source_signature") or "") or None
    return None


def _remember_source_metadata(metadata: dict[str, Any]) -> None:
    source = metadata.get("source")
    if not source:
        return
    _persist_source_context(
        {
            "path": str(Path(str(source)).resolve()),
            "sheet": metadata.get("sheet"),
        }
    )
    signature = str(metadata.get("source_signature") or "")
    if not signature:
        return
    key = str(Path(str(source)).resolve())
    sheet = metadata.get("sheet")
    if sheet is not None:
        key_with_sheet = f"{key}::{sheet}"
        _LAST_SOURCE_SIGNATURES[key_with_sheet] = signature
        _LAST_SOURCE_LABELS[key_with_sheet] = str(
            metadata.get("file_name") or Path(key).name
        )
    _LAST_SOURCE_SIGNATURES[key] = signature
    _LAST_SOURCE_LABELS[key] = str(metadata.get("file_name") or Path(key).name)


def _row_to_dashboard_record(row: sqlite3.Row, *, include_view_model: bool) -> dict[str, Any]:
    artifact = json.loads(row["artifact"]) if row["artifact"] else {}
    record: dict[str, Any] = {
        "dashboard_id": row["dashboard_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source_signature": row["source_signature"],
        "source_label": row["source_label"],
        "source_path": row["source_path"],
        "sheet": row["sheet"],
        "dashboard_key": row["dashboard_key"],
        "revision_of": row["revision_of"],
        "revision_notes": row["revision_notes"],
        "artifact": artifact,
    }
    if include_view_model:
        record["viewModel"] = json.loads(row["view_model"])
    return record


def _load_dashboard_memory_records(
    *,
    dashboard_id: str | None = None,
    source_signature: str | None = None,
    source_path: str | None = None,
    sheet: str | int | None = None,
    dashboard_key: str | None = None,
    query: str | None = None,
    limit: int = 3,
    include_view_model: bool = True,
) -> list[dict[str, Any]]:
    conn = _connect_dashboard_memory()
    if conn is None:
        return []
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if dashboard_id:
            clauses.append("dashboard_id = ?")
            params.append(dashboard_id)
        if source_signature:
            clauses.append("source_signature = ?")
            params.append(source_signature)
        if source_path:
            resolved_source = str(Path(source_path).expanduser().resolve())
            clauses.append("source_path = ?")
            params.append(resolved_source)
        if sheet is not None:
            clauses.append("sheet = ?")
            params.append(str(sheet))
        if dashboard_key:
            clauses.append("dashboard_key = ?")
            params.append(dashboard_key)
        if query:
            clauses.append("(title LIKE ? OR source_label LIKE ? OR revision_notes LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        capped_limit = max(1, min(int(limit or 3), 20))
        rows = conn.execute(
            "SELECT * FROM dashboards"
            f"{where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            (*params, capped_limit),
        ).fetchall()
        return [
            _row_to_dashboard_record(row, include_view_model=include_view_model)
            for row in rows
        ]
    finally:
        conn.close()


def _load_latest_dashboard_by_title(
    title: str,
    *,
    source_signature: str | None = None,
    dashboard_key: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    conn = _connect_dashboard_memory()
    if conn is None:
        return []
    try:
        clauses = ["title = ?"]
        params: list[Any] = [title]
        if source_signature:
            clauses.append("source_signature = ?")
            params.append(source_signature)
        if dashboard_key:
            clauses.append("dashboard_key = ?")
            params.append(dashboard_key)
        rows = conn.execute(
            "SELECT * FROM dashboards WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, id DESC LIMIT ?",
            (*params, max(1, min(int(limit or 5), 20))),
        ).fetchall()
        return [_row_to_dashboard_record(row, include_view_model=True) for row in rows]
    finally:
        conn.close()


def _dedupe_dashboard_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        dashboard_id = str(record.get("dashboard_id") or "")
        if not dashboard_id or dashboard_id in seen:
            continue
        seen.add(dashboard_id)
        deduped.append(record)
    return deduped


def _sort_dashboard_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""),
        reverse=True,
    )


def _memory_preview(record: dict[str, Any]) -> dict[str, Any]:
    preview = {k: v for k, v in record.items() if k != "viewModel"}
    view_model = record.get("viewModel")
    if isinstance(view_model, dict):
        preview["layout"] = {
            "title": view_model.get("title"),
            "kpi_count": len(view_model.get("kpis") or []),
            "sections": [
                {
                    "title": section.get("title"),
                    "items": [
                        {
                            "title": item.get("title"),
                            "type": item.get("type"),
                            "chart_type": item.get("chart_type") or item.get("chartType"),
                        }
                        for item in (section.get("items") or [])
                        if isinstance(item, dict)
                    ],
                }
                for section in (view_model.get("sections") or [])
                if isinstance(section, dict)
            ],
        }
    return preview


def _canonical_dashboard_view_model(view_model: dict[str, Any]) -> dict[str, Any]:
    try:
        from openbench.output.generators.dashboard.normalizer import (
            normalize_dashboard_view_model,
        )
    except Exception:
        return copy_item(view_model)
    with contextlib.suppress(Exception):
        return normalize_dashboard_view_model(copy_item(view_model))
    return copy_item(view_model)


def _revision_view_model_for_merge(view_model: dict[str, Any]) -> dict[str, Any]:
    noncanonical_keys = {"components", "widgets", "panels", "cards", "charts", "items"}
    if any(isinstance(view_model.get(key), list) for key in noncanonical_keys):
        return _canonical_dashboard_view_model(view_model)
    if isinstance(view_model.get("sections"), list) or isinstance(view_model.get("kpis"), list):
        return copy_item(view_model)
    return _canonical_dashboard_view_model(view_model)


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
                "Use LIMIT when returning chart/table rows that could be large.",
            ],
        },
    }
    signature = _source_signature_from_metadata(result)
    result["source_signature"] = signature
    result["dashboard_memory"] = {
        "source_signature": signature,
        "matches": [
            _memory_preview(record)
            for record in _load_dashboard_memory_records(
                source_signature=signature,
                limit=3,
                include_view_model=True,
            )
        ],
        "instructions": (
            "If matches are present and the user asks for a similar dashboard or a revision, "
            "call load_dashboard_memory with dashboard_id before composing the next ViewModel. "
            "Reuse the previous panel structure for the same functional schema and refresh only "
            "the aggregate data."
        ),
    }
    _remember_source_metadata(result)
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


def _collect_dataset_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "data",
                "dataset",
                "dataset_id",
                "datasetId",
                "source",
            } and isinstance(item, str):
                refs.add(item)
            refs.update(_collect_dataset_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_collect_dataset_refs(item))
    return refs


def _has_empty_chart_placeholders(value: Any) -> bool:
    return bool(_empty_chart_placeholders(value))


def _empty_chart_placeholders(value: Any) -> list[dict[str, Any]]:
    chart_types = {
        "chart",
        "bar",
        "bar_chart",
        "line",
        "line_chart",
        "area",
        "area_chart",
        "pie",
        "pie_chart",
        "scatter",
        "scatter_chart",
    }
    placeholders: list[dict[str, Any]] = []
    if isinstance(value, dict):
        payload = _component_payload(value)
        kind = str(
            value.get("type")
            or value.get("component")
            or value.get("kind")
            or payload.get("type")
            or payload.get("component")
            or payload.get("kind")
            or ""
        ).lower()
        data = payload.get("data")
        if kind in chart_types and (data is None or data == []):
            placeholders.append(payload)
        for item in value.values():
            placeholders.extend(_empty_chart_placeholders(item))
    if isinstance(value, list):
        for item in value:
            placeholders.extend(_empty_chart_placeholders(item))
    return placeholders


def _component_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    for key in ("props", "parameters", "content", "value"):
        nested = item.get(key)
        if isinstance(nested, dict):
            payload.update(nested)
    return payload


def _hydrate_source_datasets(view_model: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    placeholders = _empty_chart_placeholders(view_model)
    if not placeholders or not _LAST_SOURCE_CONTEXT:
        return {}
    path = _LAST_SOURCE_CONTEXT.get("path")
    if not path:
        return {}
    df, _resolved_sheet, err = _read_dataframe(str(path), sheet=_LAST_SOURCE_CONTEXT.get("sheet"))
    if err or df is None:
        return {}
    datasets: dict[str, list[dict[str, Any]]] = {}
    used_ids: set[str] = set()
    for item in placeholders:
        dataset_id, records = _dataset_from_source_chart(df, item, used_ids)
        if dataset_id and records:
            datasets[dataset_id] = records
            used_ids.add(dataset_id)
    return datasets


def _dataset_from_source_chart(
    df: Any,
    item: dict[str, Any],
    used_ids: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    title = str(item.get("title") or item.get("label") or item.get("name") or "chart")
    x_field = _chart_field(item, ("x_field", "xField", "x", "x_axis", "xAxis", "label_column"))
    y_field = _chart_field(item, ("y_field", "yField", "y", "y_axis", "yAxis", "value_column"))
    category = _resolve_source_category_column(df, x_field, title)
    metric = _resolve_source_metric_column(df, y_field)
    if not category or not metric:
        return "", []
    pd = _load_pandas()
    assert pd is not None
    grouped = df.groupby(category, dropna=False)[metric].sum().reset_index()
    output_metric = y_field if y_field and y_field not in set(map(str, df.columns)) else metric
    if output_metric != metric:
        grouped = grouped.rename(columns={metric: output_metric})
    records = _records(grouped, 200)
    return _unique_dataset_id(_slugify_id(title), used_ids), records


def _chart_field(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("property") or value.get("field") or value.get("column")
        if value is not None and str(value).strip():
            return str(value).strip()
    options = item.get("options")
    if isinstance(options, dict):
        return _chart_field(options, keys)
    return ""


def _resolve_source_category_column(df: Any, requested: str, title: str) -> str:
    columns = [str(column) for column in df.columns]
    by_lower = {column.lower(): column for column in columns}
    if requested and requested.lower() in by_lower:
        return by_lower[requested.lower()]
    preferred = _preferred_category_columns(title)
    for token in preferred:
        for column in columns:
            if token in column.lower() and not _is_numeric_column(df, column):
                return column
    tokens = _field_tokens(f"{requested} {title}")
    best_column = ""
    best_score = 0
    for column in columns:
        score = len(tokens & _field_tokens(column))
        if score > best_score and not _is_numeric_column(df, column):
            best_column = column
            best_score = score
    if best_column:
        return best_column
    for column in columns:
        if not _is_numeric_column(df, column):
            return column
    return ""


def _preferred_category_columns(title: str) -> tuple[str, ...]:
    lowered = title.lower()
    if "payment" in lowered or "cash" in lowered:
        return ("cash", "payment", "method", "type")
    if "time of day" in lowered or "hour" in lowered:
        return ("time_of_day", "time", "hour")
    if "day of week" in lowered or "weekday" in lowered or "week day" in lowered:
        return ("weekday", "day", "date")
    if "monthly" in lowered or "month" in lowered:
        return ("month", "date")
    if "daily" in lowered or "date" in lowered:
        return ("date", "day")
    if "coffee" in lowered or "product" in lowered or "type" in lowered:
        return ("coffee", "product", "name", "type")
    return ()


def _resolve_source_metric_column(df: Any, requested: str) -> str:
    columns = [str(column) for column in df.columns]
    by_lower = {column.lower(): column for column in columns}
    if requested and requested.lower() in by_lower and _is_numeric_column(df, by_lower[requested.lower()]):
        return by_lower[requested.lower()]
    preferred = ("sales", "revenue", "money", "amount", "total", "value", "price")
    for token in preferred:
        for column in columns:
            if token in column.lower() and _is_numeric_column(df, column):
                return column
    for column in columns:
        if _is_numeric_column(df, column):
            return column
    return ""


def _is_numeric_column(df: Any, column: str) -> bool:
    pd = _load_pandas()
    return bool(pd is not None and pd.api.types.is_numeric_dtype(df[column]))


def _field_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if len(token) > 1}


def _slugify_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "dataset"


def _unique_dataset_id(base: str, used_ids: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _hydrate_cached_datasets(view_model: dict[str, Any]) -> dict[str, Any]:
    _restore_dashboard_state()
    current = view_model.get("datasets")
    datasets = dict(current) if isinstance(current, dict) else {}
    missing: dict[str, list[dict[str, Any]]] = {}
    dataset_refs = _collect_dataset_refs(view_model)
    if not dataset_refs and _has_empty_chart_placeholders(view_model):
        dataset_refs = set(_LAST_AGGREGATE_DATASETS)
    for dataset_id in dataset_refs:
        if dataset_id not in datasets and dataset_id in _LAST_AGGREGATE_DATASETS:
            missing[dataset_id] = _LAST_AGGREGATE_DATASETS[dataset_id]
    if not missing and _has_empty_chart_placeholders(view_model):
        for dataset_id, records in _hydrate_source_datasets(view_model).items():
            if dataset_id not in datasets:
                missing[dataset_id] = records
    if not missing:
        return view_model

    hydrated = dict(view_model)
    hydrated["datasets"] = {**datasets, **missing}
    return hydrated


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
        "source_signature": _source_signature_for_path(str(p), sheet=resolved_sheet),
        "dialect": "sqlite",
        "table": str(table_name),
        "datasets": datasets,
        "errors": errors,
    }
    _remember_source_metadata(
        {
            "source": str(p.resolve()),
            "sheet": _json_value(resolved_sheet),
            "source_signature": str(result.get("source_signature") or ""),
            "file_name": p.name,
        }
    )
    _remember_aggregate_datasets(datasets)
    return result


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


def _dashboard_template_options(
    *,
    template_path: str | None = None,
    template_text: str | None = None,
    template_format: str | None = None,
) -> dict[str, Any] | None:
    if not template_path and not template_text:
        return None
    result: dict[str, Any] = {}
    if template_path:
        result["template_path"] = template_path
        with contextlib.suppress(Exception):
            result["template_text"] = Path(template_path).read_text(encoding="utf-8")
    if template_text:
        result["template_text"] = template_text
    if template_format:
        result["template_format"] = template_format
    return result


def _write_dashboard_export(
    view_model: dict[str, Any],
    output_path: Path,
    *,
    dashboard_template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapters = _load_adapters_module()
    adapter = adapters.create_dashboard_adapter(
        output_path=output_path,
        public_url=_public_url(output_path),
        adapter=_DASHBOARD_ADAPTER,
        adapter_factory=_DASHBOARD_ADAPTER_FACTORY,
        dashboard_template=dashboard_template,
    )
    rendered = adapter.render(view_model)
    if hasattr(rendered, "to_dict") and callable(rendered.to_dict):
        return rendered.to_dict()
    if isinstance(rendered, dict):
        return rendered
    raise TypeError("Dashboard adapter render() must return a dict or DashboardRenderResult")


def _item_key(item: dict[str, Any]) -> str | None:
    for key in ("id", "panel_id", "panelId", "title", "label"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return None


def _normalise_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalise_match_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _allowed_revision_keys(
    previous: dict[str, Any],
    patch: dict[str, Any],
    *,
    revision_notes: str | None = None,
    revision_panel_titles: list[str] | None = None,
) -> set[str]:
    explicit = {
        _normalise_match_key(title)
        for title in (revision_panel_titles or [])
        if str(title or "").strip()
    }
    if explicit:
        return explicit

    notes = _normalise_match_text(revision_notes)
    if not notes:
        return set()

    allowed: set[str] = set()
    for item in _dashboard_items(previous) + _dashboard_items(patch):
        if not isinstance(item, dict):
            continue
        for key in ("id", "panel_id", "panelId", "title", "label"):
            value = item.get(key)
            if not value:
                continue
            normalized_value = _normalise_match_text(value)
            if normalized_value and normalized_value in notes:
                allowed.add(_normalise_match_key(value))
    return allowed


def _dashboard_items(view_model: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for kpi in view_model.get("kpis") or []:
        if isinstance(kpi, dict):
            items.append(kpi)
    for section in view_model.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if isinstance(item, dict):
                items.append(item)
    return items


def _dashboard_item_map(view_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: item
        for item in _dashboard_items(view_model)
        for key in [_normalise_match_key(_item_key(item))]
        if key
    }


def _patch_item_keys(view_model: dict[str, Any]) -> set[str]:
    return {
        key
        for item in _dashboard_items(view_model)
        for key in [_normalise_match_key(_item_key(item))]
        if key
    }


def _panel_overlap_score(previous: dict[str, Any], patch: dict[str, Any]) -> tuple[int, int]:
    previous_keys = _patch_item_keys(previous)
    patch_keys = _patch_item_keys(patch)
    if not previous_keys or not patch_keys:
        return (0, max(len(previous_keys), len(patch_keys)))
    return (len(previous_keys & patch_keys), max(len(previous_keys), len(patch_keys)))


def _has_revision_overlap(previous: dict[str, Any], patch: dict[str, Any]) -> bool:
    overlap, total = _panel_overlap_score(previous, patch)
    if overlap <= 0:
        return False
    if total <= 2:
        return overlap == total
    return overlap >= 2 and overlap / max(total, 1) >= 0.5


def _load_revision_candidates(
    view_model: dict[str, Any],
    *,
    source_signature: str | None = None,
    source_path: str | None = None,
    sheet: str | int | None = None,
    dashboard_key: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if source_signature or source_path or dashboard_key:
        candidates.extend(
            _load_dashboard_memory_records(
                source_signature=source_signature,
                source_path=source_path,
                sheet=sheet,
                dashboard_key=dashboard_key,
                limit=limit,
                include_view_model=True,
            )
        )
    title = str(view_model.get("title") or "").strip()
    if title:
        candidates.extend(
            _load_latest_dashboard_by_title(
                title,
                source_signature=source_signature,
                dashboard_key=dashboard_key,
                limit=limit,
            )
        )
    recent = _load_dashboard_memory_records(limit=limit, include_view_model=True)
    if title and (source_signature or dashboard_key):
        candidates.extend(_load_latest_dashboard_by_title(title, limit=limit))
    candidates.extend(
        record
        for record in recent
        if isinstance(record.get("viewModel"), dict)
        and _has_revision_overlap(record["viewModel"], view_model)
    )
    return _sort_dashboard_records(_dedupe_dashboard_records(candidates))


_DASHBOARD_BINDING_KEYS = {
    "data",
    "dataset",
    "dataset_id",
    "datasetId",
    "source",
    "x_field",
    "xField",
    "y_field",
    "yField",
    "value_field",
    "valueField",
    "label_field",
    "labelField",
    "category_field",
    "categoryField",
    "series_field",
    "seriesField",
    "fields",
    "columns",
    "view_data",
    "viewData",
}


def _item_has_data_payload(item: dict[str, Any]) -> bool:
    for key in ("data", "view_data", "viewData"):
        data = item.get(key)
        if isinstance(data, list) and data:
            return True
        if isinstance(data, dict) and data:
            return True
    for key in {"dataset", "dataset_id", "datasetId", "source"}:
        if item.get(key):
            return True
    return False


def _item_changed_for_revision(previous_item: dict[str, Any], patch_item: dict[str, Any]) -> bool:
    patch_has_data = _item_has_data_payload(patch_item)
    for key, value in patch_item.items():
        if key in _DASHBOARD_BINDING_KEYS and not patch_has_data and key in previous_item:
            continue
        if value in (None, "", [], {}) and key not in previous_item:
            continue
        if copy_item(value) != copy_item(previous_item.get(key)):
            return True
    return False


def _changed_patch_keys(previous: dict[str, Any], patch: dict[str, Any]) -> set[str]:
    previous_items = _dashboard_item_map(previous)
    changed: set[str] = set()
    for key, item in _dashboard_item_map(patch).items():
        previous_item = previous_items.get(key)
        if previous_item is None or _item_changed_for_revision(previous_item, item):
            changed.add(key)
    return changed


def _changed_patch_keys_in_order(previous: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    previous_items = _dashboard_item_map(previous)
    ordered: list[str] = []
    seen: set[str] = set()
    for item in _dashboard_items(patch):
        key = _normalise_match_key(_item_key(item))
        if not key or key in seen:
            continue
        previous_item = previous_items.get(key)
        if previous_item is None or _item_changed_for_revision(previous_item, item):
            ordered.append(key)
            seen.add(key)
    return ordered


def _select_revision_record(
    records: list[dict[str, Any]],
    patch: dict[str, Any],
    *,
    revision_notes: str | None = None,
    revision_panel_titles: list[str] | None = None,
) -> dict[str, Any] | None:
    fallback = _sort_dashboard_records(records)[0] if records else None
    best: tuple[int, str, dict[str, Any]] | None = None
    for record in records:
        view_model = record.get("viewModel")
        if not isinstance(view_model, dict):
            continue
        changed_keys = set(_changed_patch_keys_in_order(view_model, patch))
        if not changed_keys:
            continue
        allowed_keys = _allowed_revision_keys(
            view_model,
            patch,
            revision_notes=revision_notes,
            revision_panel_titles=revision_panel_titles,
        )
        score = 1
        if allowed_keys and changed_keys & allowed_keys:
            score = 3
        elif allowed_keys:
            score = 0
        updated_at = str(record.get("updated_at") or record.get("created_at") or "")
        candidate = (score, updated_at, record)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best is not None else fallback


def _select_auto_revision_record(
    records: list[dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    return _select_revision_record(records, patch)


def _items_matching_keys(view_model: dict[str, Any], keys: set[str]) -> list[dict[str, Any]]:
    return [
        item
        for item in _dashboard_items(view_model)
        if _normalise_match_key(_item_key(item)) in keys
    ]


def _merge_dashboard_item(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    next_item = copy_item(current)
    patch_item = copy_item(patch)
    if not _item_has_data_payload(patch_item) and _item_has_data_payload(next_item):
        for key in _DASHBOARD_BINDING_KEYS:
            if key in next_item and key in patch_item:
                patch_item.pop(key, None)
    next_item.update(patch_item)
    return next_item


def _merge_item_lists(
    previous: list[Any],
    patch: list[Any],
    *,
    allowed_revision_keys: set[str] | None = None,
) -> tuple[list[Any], list[str]]:
    merged = [copy_item(item) for item in previous]
    key_to_index = {
        _normalise_match_key(key): index
        for index, item in enumerate(merged)
        if isinstance(item, dict)
        for key in [_item_key(item)]
        if key
    }
    applied: list[str] = []
    for item in patch:
        if not isinstance(item, dict):
            continue
        key = _item_key(item)
        normalized_key = _normalise_match_key(key)
        if (
            allowed_revision_keys is not None
            and normalized_key not in allowed_revision_keys
        ):
            continue
        if key and normalized_key in key_to_index:
            current = merged[key_to_index[normalized_key]]
            merged[key_to_index[normalized_key]] = (
                _merge_dashboard_item(current, item) if isinstance(current, dict) else item
            )
            applied.append(str(key))
        else:
            merged.append(copy_item(item))
            if key:
                applied.append(str(key))
    return merged, applied


def copy_item(value: Any) -> Any:
    return json.loads(_json_dumps(value))


def _merge_sections(
    previous: list[Any],
    patch: list[Any],
    *,
    allowed_revision_keys: set[str] | None = None,
) -> tuple[list[Any], list[str]]:
    merged = [copy_item(section) for section in previous if isinstance(section, dict)]
    key_to_index = {
        key: index
        for index, section in enumerate(merged)
        for key in [_item_key(section)]
        if key
    }
    applied: list[str] = []
    for section in patch:
        if not isinstance(section, dict):
            continue
        key = _item_key(section)
        if key and key in key_to_index:
            current = merged[key_to_index[key]]
            next_section = {**current, **section}
            current_items = current.get("items") if isinstance(current.get("items"), list) else []
            patch_items = section.get("items") if isinstance(section.get("items"), list) else []
            if patch_items:
                next_items, item_applied = _merge_item_lists(
                    current_items,
                    patch_items,
                    allowed_revision_keys=allowed_revision_keys,
                )
                next_section["items"] = next_items
                applied.extend(item_applied)
            merged[key_to_index[key]] = next_section
        else:
            if allowed_revision_keys is None or _normalise_match_key(key) in allowed_revision_keys:
                merged.append(copy_item(section))
                if key:
                    applied.append(str(key))
    return merged, applied


def _merge_dashboard_revision(
    previous: dict[str, Any],
    patch: dict[str, Any],
    *,
    revision_notes: str | None = None,
    revision_panel_titles: list[str] | None = None,
    auto_revision: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = copy_item(previous)
    allowed_keys = _allowed_revision_keys(
        previous,
        patch,
        revision_notes=revision_notes,
        revision_panel_titles=revision_panel_titles,
    )
    if not allowed_keys and revision_notes:
        patch_keys = _patch_item_keys(patch)
        previous_keys = _patch_item_keys(previous)
        changed_keys = _changed_patch_keys(previous, patch)
        if patch_keys and len(patch_keys) < len(previous_keys):
            allowed_keys = patch_keys
        elif len(changed_keys) == 1:
            allowed_keys = changed_keys
    if not allowed_keys and auto_revision:
        changed_order = _changed_patch_keys_in_order(previous, patch)
        if changed_order:
            allowed_keys = {changed_order[0]}
    strict_panel_merge = (
        bool(allowed_keys)
        or bool(revision_notes or revision_panel_titles)
        or auto_revision
    )
    applied: list[str] = []
    if isinstance(patch.get("kpis"), list):
        previous_kpis = previous.get("kpis") if isinstance(previous.get("kpis"), list) else []
        merged["kpis"], kpi_applied = _merge_item_lists(
            previous_kpis,
            patch["kpis"],
            allowed_revision_keys=allowed_keys if strict_panel_merge else None,
        )
        applied.extend(kpi_applied)
    if isinstance(patch.get("sections"), list):
        previous_sections = (
            previous.get("sections") if isinstance(previous.get("sections"), list) else []
        )
        merged["sections"], section_applied = _merge_sections(
            previous_sections,
            patch["sections"],
            allowed_revision_keys=allowed_keys if strict_panel_merge else None,
        )
        applied.extend(section_applied)
    applied_keys = {_normalise_match_key(key) for key in applied}
    for key, value in patch.items():
        if key in {"sections", "kpis"}:
            continue
        if strict_panel_merge:
            continue
        merged[key] = copy_item(value)
    if strict_panel_merge and isinstance(patch.get("datasets"), dict):
        dataset_refs = _collect_dataset_refs(_items_matching_keys(patch, applied_keys))
        dataset_refs.update(
            _collect_dataset_refs(_items_matching_keys(previous, applied_keys))
        )
        if dataset_refs:
            previous_datasets = (
                previous.get("datasets") if isinstance(previous.get("datasets"), dict) else {}
            )
            merged_datasets = copy_item(previous_datasets)
            for dataset_id in dataset_refs:
                if dataset_id in patch["datasets"]:
                    merged_datasets[dataset_id] = copy_item(patch["datasets"][dataset_id])
            merged["datasets"] = merged_datasets
    return merged, {
        "strict_panel_merge": strict_panel_merge,
        "auto_revision": auto_revision,
        "allowed_keys": sorted(allowed_keys),
        "applied_keys": sorted(set(applied)),
    }


def load_dashboard_memory(
    dashboard_id: str | None = None,
    source_path: str | None = None,
    sheet: str | int | None = None,
    source_signature: str | None = None,
    dashboard_key: str | None = None,
    query: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Load persisted dashboard ViewModels for consistency or revision."""
    resolved_signature = source_signature
    if not resolved_signature and source_path:
        resolved_signature = _source_signature_for_path(source_path, sheet=sheet)
    records = _load_dashboard_memory_records(
        dashboard_id=dashboard_id,
        source_signature=resolved_signature,
        source_path=source_path,
        sheet=sheet,
        dashboard_key=dashboard_key,
        query=query,
        limit=limit,
        include_view_model=True,
    )
    return {
        "type": "dashboard_memory",
        "source_signature": resolved_signature,
        "count": len(records),
        "records": records,
        "instructions": (
            "For revisions, use the returned viewModel as the base. Change only the requested "
            "panel/KPI/section and pass previous_dashboard_id to generate_dashboard so "
            "unspecified panels are preserved."
        ),
    }


def _store_dashboard_memory(
    *,
    view_model: dict[str, Any],
    item: dict[str, Any],
    source_signature: str | None,
    source_label: str | None,
    source_path: str | None,
    sheet: str | int | None,
    dashboard_key: str | None,
    dashboard_id: str,
    revision_of: str | None,
    revision_notes: str | None,
) -> None:
    conn = _connect_dashboard_memory()
    if conn is None:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO dashboards (
                dashboard_id, created_at, updated_at, title, source_signature,
                source_label, source_path, sheet, dashboard_key, view_model,
                artifact, revision_of, revision_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dashboard_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                title = excluded.title,
                source_signature = excluded.source_signature,
                source_label = excluded.source_label,
                source_path = excluded.source_path,
                sheet = excluded.sheet,
                dashboard_key = excluded.dashboard_key,
                view_model = excluded.view_model,
                artifact = excluded.artifact,
                revision_of = excluded.revision_of,
                revision_notes = excluded.revision_notes
            """,
            (
                dashboard_id,
                now,
                now,
                str(view_model.get("title") or "OpenBench Dashboard"),
                source_signature,
                source_label,
                str(Path(source_path).expanduser().resolve()) if source_path else None,
                str(sheet) if sheet is not None else None,
                dashboard_key,
                _json_dumps(view_model),
                _json_dumps(
                    {
                        "name": item.get("name"),
                        "url": item.get("url"),
                        "dashboardUrl": item.get("dashboardUrl"),
                        "path": item.get("path"),
                        "render_mode": item.get("render_mode"),
                        "templateSource": item.get("templateSource"),
                        "templateFormat": item.get("templateFormat"),
                        "templateName": item.get("templateName"),
                    }
                ),
                revision_of,
                revision_notes,
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[dashboard] failed to persist dashboard memory: %s", exc)
    finally:
        conn.close()


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
    template_path: str | None = None,
    template_text: str | None = None,
    template_format: str | None = None,
    source_path: str | None = None,
    sheet: str | int | None = None,
    dashboard_key: str | None = None,
    previous_dashboard_id: str | None = None,
    revision_notes: str | None = None,
    revision_panel_titles: list[str] | None = None,
    preserve_unspecified: bool = True,
) -> dict[str, Any]:
    """Create a dashboard artifact from a declarative ViewModel."""
    if not isinstance(view_model, dict) or not view_model:
        return _error("dashboard", "`view_model` must be a non-empty object")

    source_signature = (
        _source_signature_for_path(source_path, sheet=sheet) if source_path else None
    )
    source_label = None
    if source_path:
        source_key = str(Path(source_path).expanduser().resolve())
        if sheet is not None:
            source_label = _LAST_SOURCE_LABELS.get(f"{source_key}::{sheet}")
        source_label = (
            source_label or _LAST_SOURCE_LABELS.get(source_key) or Path(source_path).name
        )
    canonical_revision_view_model: dict[str, Any] | None = None

    revision_of = previous_dashboard_id
    previous_records: list[dict[str, Any]] = []
    auto_revision = False
    if previous_dashboard_id and preserve_unspecified:
        previous_records = _load_dashboard_memory_records(
            dashboard_id=previous_dashboard_id,
            limit=1,
            include_view_model=True,
        )
    elif (
        preserve_unspecified
        and (revision_notes or revision_panel_titles)
    ):
        canonical_revision_view_model = _revision_view_model_for_merge(view_model)
        candidates = _load_revision_candidates(
            canonical_revision_view_model,
            source_signature=source_signature,
            source_path=source_path,
            sheet=sheet,
            dashboard_key=dashboard_key,
        )
        selected = _select_revision_record(
            candidates,
            canonical_revision_view_model,
            revision_notes=revision_notes,
            revision_panel_titles=revision_panel_titles,
        )
        previous_records = [selected] if selected else []
        if previous_records:
            revision_of = previous_records[0].get("dashboard_id")
    elif preserve_unspecified:
        canonical_revision_view_model = _revision_view_model_for_merge(view_model)
        candidates = _load_revision_candidates(
            canonical_revision_view_model,
            source_signature=source_signature,
            source_path=source_path,
            sheet=sheet,
            dashboard_key=dashboard_key,
        )
        selected = _select_auto_revision_record(candidates, canonical_revision_view_model)
        previous_records = [selected] if selected else []
        if previous_records:
            revision_of = previous_records[0].get("dashboard_id")
            auto_revision = True

    revision_merge: dict[str, Any] = {}
    if previous_records and isinstance(previous_records[0].get("viewModel"), dict):
        previous_view_model = previous_records[0]["viewModel"]
        revision_view_model = canonical_revision_view_model or _revision_view_model_for_merge(
            view_model
        )
        view_model, revision_merge = _merge_dashboard_revision(
            previous_view_model,
            revision_view_model,
            revision_notes=revision_notes,
            revision_panel_titles=revision_panel_titles,
            auto_revision=auto_revision,
        )
        source_signature = source_signature or previous_records[0].get("source_signature")
        source_label = source_label or previous_records[0].get("source_label")
        source_path = source_path or previous_records[0].get("source_path")
        sheet = sheet if sheet is not None else previous_records[0].get("sheet")
        dashboard_key = dashboard_key or previous_records[0].get("dashboard_key")

    view_model = _hydrate_cached_datasets(view_model)
    title = str(view_model.get("title") or "OpenBench Dashboard")
    out_dir = Path(output_dir or os.environ.get("OPENBENCH_EXPORT_DIR") or "outputs").resolve()
    out_name = _unique_dashboard_filename(title, filename)
    out_path = out_dir / out_name
    dashboard_template = _dashboard_template_options(
        template_path=template_path,
        template_text=template_text,
        template_format=template_format,
    )
    written = _write_dashboard_export(
        view_model,
        out_path,
        dashboard_template=dashboard_template,
    )
    url = _public_url(out_path)
    rendered_view_model = written.get("viewModel") or written.get("view_model") or view_model
    if isinstance(rendered_view_model, dict):
        view_model = rendered_view_model
    datasets = (
        rendered_view_model.get("datasets", {}) if isinstance(rendered_view_model, dict) else {}
    )
    kpis = rendered_view_model.get("kpis", []) if isinstance(rendered_view_model, dict) else []
    sections = (
        rendered_view_model.get("sections", []) if isinstance(rendered_view_model, dict) else []
    )
    warnings = (
        rendered_view_model.pop("normalization_warnings", [])
        if isinstance(rendered_view_model, dict)
        else []
    )
    panels = [
        panel
        for section in (sections if isinstance(sections, list) else [])
        if isinstance(section, dict)
        for panel in section.get("items", [])
        if isinstance(panel, dict)
    ]
    chart_count = sum(1 for panel in panels if panel.get("type") == "chart")
    table_count = sum(1 for panel in panels if panel.get("type") == "table")
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
        "chartCount": chart_count,
        "tableCount": table_count,
        "warnings": warnings,
        "adapter": written.get("adapter", {}),
        "stitch": written.get("stitch", {}),
        "customTemplate": written.get("custom_template"),
        "templateSource": written.get("template_source") or (
            "user" if written.get("custom_template") else "default"
        ),
        "templateFormat": written.get("template_format")
        or (written.get("custom_template") or {}).get("format")
        or "default",
        "templateName": written.get("template_name")
        or (written.get("custom_template") or {}).get("source")
        or "openbench",
    }
    dashboard_id = _dashboard_id(view_model, source_signature)
    item["dashboardId"] = dashboard_id
    item["dashboard_id"] = dashboard_id
    item["sourceSignature"] = source_signature
    item["source_signature"] = source_signature
    item["sourceLabel"] = source_label
    item["sourcePath"] = source_path
    item["dashboardKey"] = dashboard_key
    item["revisionOf"] = revision_of
    item["revisionNotes"] = revision_notes
    item["revisionPanelTitles"] = revision_panel_titles or []
    item["revisionMerge"] = revision_merge
    item["memory"] = {
        "persisted": _dashboard_memory_enabled(),
        "dashboard_id": dashboard_id,
        "source_signature": source_signature,
        "revision_of": revision_of,
    }
    logger.info(
        "[dashboard] artifact created render_mode=%s template_source=%s template_format=%s "
        "template_name=%s title=%s datasets=%d kpis=%d sections=%d charts=%d tables=%d "
        "warnings=%d dashboard_id=%s",
        item.get("render_mode"),
        item.get("templateSource"),
        item.get("templateFormat"),
        item.get("templateName"),
        item.get("title"),
        len(item.get("datasets") or {}),
        len(item.get("kpis") or []),
        len(item.get("sections") or []),
        chart_count,
        table_count,
        len(warnings),
        dashboard_id,
    )
    _store_dashboard_memory(
        view_model=view_model,
        item=item,
        source_signature=source_signature,
        source_label=source_label,
        source_path=source_path,
        sheet=sheet,
        dashboard_key=dashboard_key,
        dashboard_id=dashboard_id,
        revision_of=revision_of,
        revision_notes=revision_notes,
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
    "must use the canonical OpenBench shape: title, kpis, sections[].items[]. "
    "KPI cards are {label, value, value_format}. Chart panels are "
    "{type:'chart', chart_type, title, data:[rows], x_field, y_field}. "
    "Table panels are {type:'table', title, data:[rows], columns}. "
    "Prefer this canonical shape over props/content/components/Chart.js dialects. "
    "Do not include raw UI code. The generated dashboard is persisted to dashboard "
    "memory. For revisions, pass previous_dashboard_id and only the changed panel; "
    "unspecified panels are preserved by default.",
    {
        "view_model": {
            "type": "object",
            "description": (
                "Canonical dashboard ViewModel: {title, optional description, "
                "kpis:[{label,value,value_format}], sections:[{title, items:["
                "{type:'chart', chart_type, title, data, x_field, y_field} or "
                "{type:'table', title, data, columns}]}]}. The backend has a "
                "normalizer fallback, but tool callers should emit this shape."
            ),
        },
        "filename": {"type": "string", "description": "Optional .html filename"},
        "output_dir": {"type": "string", "description": "Optional output directory"},
        "template_path": {
            "type": "string",
            "description": (
                "Optional uploaded dashboard template path. Accepts .html/.htm templates "
                "or markdown design briefs such as design.md."
            ),
        },
        "template_text": {
            "type": "string",
            "description": "Optional inline dashboard template or markdown design brief.",
        },
        "template_format": {
            "type": "string",
            "description": "Optional template format: html or markdown.",
        },
        "source_path": {
            "type": "string",
            "description": (
                "Optional CSV/XLSX source path used to compute a functional schema "
                "signature for cross-session dashboard consistency."
            ),
        },
        "sheet": {"type": "string", "description": "Optional Excel sheet name"},
        "dashboard_key": {
            "type": "string",
            "description": "Optional stable user/business key for this dashboard family.",
        },
        "previous_dashboard_id": {
            "type": "string",
            "description": (
                "Dashboard memory id to revise. When set, the previous ViewModel is "
                "used as the base and only matching supplied panels/KPIs/sections are changed."
            ),
        },
        "revision_notes": {
            "type": "string",
            "description": "Optional natural-language note describing the user-requested revision.",
        },
        "revision_panel_titles": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Exact titles/ids/labels of panels or KPIs the user asked to revise. "
                "When set, only these panels may change; all other panels are restored "
                "from dashboard memory even if the ViewModel includes them."
            ),
        },
        "preserve_unspecified": {
            "type": "boolean",
            "description": (
                "Defaults to true for revisions. Keep old panels/KPIs/sections that are not "
                "mentioned in the new ViewModel patch."
            ),
        },
    },
    ["view_model"],
)

LOAD_DASHBOARD_MEMORY_SCHEMA = _schema(
    "load_dashboard_memory",
    "Load previously generated dashboard ViewModels from persistent memory. Use this before "
    "recreating a dashboard for the same functional source schema, or before applying a user "
    "revision so unchanged panels can be preserved.",
    {
        "dashboard_id": {"type": "string", "description": "Exact dashboard memory id."},
        "source_path": {
            "type": "string",
            "description": (
                "CSV/XLSX source path; the tool derives the functional schema signature."
            ),
        },
        "sheet": {"type": "string", "description": "Optional Excel sheet name"},
        "source_signature": {
            "type": "string",
            "description": "Functional schema signature returned by extract_metadata.",
        },
        "dashboard_key": {
            "type": "string",
            "description": "Optional stable user/business key for a dashboard family.",
        },
        "query": {
            "type": "string",
            "description": "Optional title/source/revision keyword search.",
        },
        "limit": {"type": "integer", "description": "Maximum records to return, default 3."},
    },
    [],
)
