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
import copy
import hashlib
import html
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
    "search_dashboards",
    "load_dashboard",
    "EXTRACT_METADATA_SCHEMA",
    "AGGREGATE_DATA_SCHEMA",
    "GENERATE_DASHBOARD_SCHEMA",
    "SEARCH_DASHBOARDS_SCHEMA",
    "LOAD_DASHBOARD_SCHEMA",
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
_LAST_AGGREGATE_DATASETS: dict[str, list[dict[str, Any]]] = {}
_LAST_SOURCE_CONTEXT: dict[str, Any] = {}
_MAX_DASHBOARD_MEMORY_ITEMS = 100
_HTML_BACKFILL_SCRIPT_RE = re.compile(
    r'<script[^>]+id=["\']openbench-dashboard-view-model["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _dashboard_state_path() -> Path:
    raw = (
        os.environ.get("OPENBENCH_DASHBOARD_STATE_PATH")
        or os.environ.get("GENERAL_CHAT_DASHBOARD_STATE_PATH")
    )
    if raw:
        return Path(raw).expanduser().resolve()
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json_hash(value: Any, length: int = 16) -> str:
    payload = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _state_dashboards(state: dict[str, Any]) -> list[dict[str, Any]]:
    dashboards = state.get("dashboards")
    return [item for item in dashboards if isinstance(item, dict)] if isinstance(dashboards, list) else []


def _source_context_from_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    if _LAST_SOURCE_CONTEXT:
        return dict(_LAST_SOURCE_CONTEXT)
    loaded = state if isinstance(state, dict) else _load_dashboard_state()
    source_context = loaded.get("source_context")
    return dict(source_context) if isinstance(source_context, dict) else {}


def _source_signature_from_path(raw_path: Any, *, sheet: Any = None) -> dict[str, Any]:
    signature: dict[str, Any] = {
        "path": str(raw_path) if raw_path else "",
        "sheet": _json_value(sheet),
    }
    if not raw_path:
        return signature

    path = Path(str(raw_path))
    signature["file_name"] = path.name
    if not path.exists():
        signature["missing"] = True
        signature["source_key"] = _stable_json_hash(signature)
        return signature

    signature["path"] = str(path.resolve())
    with contextlib.suppress(Exception):
        signature["file_hash"] = _file_hash(path)

    df, resolved_sheet, err = _read_dataframe(str(path), sheet=sheet)
    if err or df is None:
        signature["read_error"] = err
        signature["source_key"] = _stable_json_hash(signature)
        return signature

    columns = [{"name": str(column), "dtype": str(df[column].dtype)} for column in df.columns]
    signature.update(
        {
            "sheet": _json_value(resolved_sheet),
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": columns,
            "schema_hash": _stable_json_hash({"columns": columns, "row_count": int(len(df))}),
        }
    )
    signature["source_key"] = _stable_json_hash(
        {
            "file_hash": signature.get("file_hash"),
            "sheet": signature.get("sheet"),
            "schema_hash": signature.get("schema_hash"),
        }
    )
    return signature


def _source_signature(state: dict[str, Any] | None = None) -> dict[str, Any]:
    context = _source_context_from_state(state)
    return _source_signature_from_path(context.get("path"), sheet=context.get("sheet"))


def _template_signature(
    *,
    template_path: str | None = None,
    template_text: str | None = None,
    template_format: str | None = None,
) -> dict[str, Any]:
    signature: dict[str, Any] = {"format": template_format or "default", "source": "default"}
    if template_path:
        path = Path(template_path).expanduser()
        signature.update({"source": "path", "path": str(path), "file_name": path.name})
        if path.exists():
            resolved = path.resolve()
            signature["path"] = str(resolved)
            with contextlib.suppress(Exception):
                signature["file_hash"] = _file_hash(resolved)
        if signature.get("file_hash"):
            signature["template_key"] = _stable_json_hash(
                {
                    "source": "path",
                    "file_hash": signature.get("file_hash"),
                    "format": signature.get("format"),
                }
            )
            return signature
        signature["template_key"] = _stable_json_hash(signature)
        return signature
    if template_text:
        signature.update({"source": "inline", "text_hash": _stable_json_hash(template_text, 24)})
    signature["template_key"] = _stable_json_hash(signature)
    return signature


def _dashboard_match_key(source: dict[str, Any], template: dict[str, Any]) -> str:
    if source.get("file_hash") or source.get("schema_hash"):
        payload = {
            "source_key": source.get("source_key"),
            "file_hash": source.get("file_hash"),
            "sheet": source.get("sheet"),
            "schema_hash": source.get("schema_hash"),
            "template_key": template.get("template_key"),
        }
    else:
        payload = {
            "source": source,
            "template_key": template.get("template_key"),
        }
    return _stable_json_hash(payload, 24)


def _dashboard_summary(
    entry: dict[str, Any],
    *,
    exact_source_match: bool | None = None,
    exact_template_match: bool | None = None,
) -> dict[str, Any]:
    artifact = entry.get("artifact") if isinstance(entry.get("artifact"), dict) else {}
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    template = entry.get("template") if isinstance(entry.get("template"), dict) else {}
    summary = {
        "dashboard_id": entry.get("id"),
        "title": entry.get("title") or artifact.get("title"),
        "description": entry.get("description") or artifact.get("description"),
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
        "url": artifact.get("dashboardUrl") or artifact.get("url"),
        "path": artifact.get("path"),
        "source_file": source.get("file_name"),
        "source_path": source.get("path"),
        "source_hash": source.get("file_hash"),
        "sheet": source.get("sheet"),
        "template_source": template.get("source"),
        "template_name": template.get("file_name") or artifact.get("templateName"),
        "template_hash": template.get("file_hash"),
        "kpi_count": artifact.get("kpiCount"),
        "chart_count": artifact.get("chartCount"),
        "table_count": artifact.get("tableCount"),
    }
    if exact_source_match is not None:
        summary["exact_source_match"] = exact_source_match
    if exact_template_match is not None:
        summary["exact_template_match"] = exact_template_match
    if exact_source_match is not None or exact_template_match is not None:
        summary["reusable_match"] = bool(exact_source_match) and (
            exact_template_match is not False
        )
    return summary


def _dashboard_artifact_from_view_model(
    view_model: dict[str, Any],
    path: Path,
    *,
    source: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    title = str(view_model.get("title") or _html_title(path) or path.stem)
    datasets = view_model.get("datasets", {}) if isinstance(view_model, dict) else {}
    kpis = view_model.get("kpis", []) if isinstance(view_model, dict) else []
    sections = view_model.get("sections", []) if isinstance(view_model, dict) else []
    panels = [
        panel
        for section in (sections if isinstance(sections, list) else [])
        if isinstance(section, dict)
        for panel in section.get("items", [])
        if isinstance(panel, dict)
    ]
    return {
        "type": "dashboard",
        "title": title,
        "description": str(view_model.get("description") or ""),
        "render_mode": "a2ui",
        "renderMode": "a2ui",
        "viewModel": view_model,
        "datasets": datasets if isinstance(datasets, dict) else {},
        "kpis": kpis if isinstance(kpis, list) else [],
        "sections": sections if isinstance(sections, list) else [],
        "name": path.name,
        "url": _public_url(path),
        "dashboardUrl": _public_url(path),
        "path": str(path),
        "mimeType": "text/html",
        "size": path.stat().st_size if path.exists() else 0,
        "summary": str(view_model.get("description") or ""),
        "sectionCount": len(sections) if isinstance(sections, list) else 0,
        "kpiCount": len(kpis) if isinstance(kpis, list) else 0,
        "chartCount": sum(1 for panel in panels if panel.get("type") == "chart"),
        "tableCount": sum(1 for panel in panels if panel.get("type") == "table"),
        "warnings": [],
        "templateSource": "imported",
        "templateFormat": "html",
        "templateName": "html-export",
        "source": source or {},
        "importedAt": created_at,
    }


def _source_signature_from_view_model(view_model: dict[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {}
    raw_source = view_model.get("source")
    if isinstance(raw_source, dict):
        raw_path = (
            raw_source.get("path")
            or raw_source.get("source_path")
            or raw_source.get("sourcePath")
        )
        raw_name = raw_source.get("file_name") or raw_source.get("fileName") or raw_source.get("name")
    elif isinstance(raw_source, str):
        raw_path = raw_source
        raw_name = ""
    else:
        raw_path = (
            view_model.get("sourcePath")
            or view_model.get("source_path")
            or view_model.get("sourceLabel")
            or view_model.get("source_label")
        )
        raw_name = ""

    if raw_path:
        path_text = str(raw_path)
        source["path"] = path_text
        source["file_name"] = raw_name or Path(path_text).name
        path = Path(path_text)
        if path.exists():
            resolved = path.resolve()
            source["path"] = str(resolved)
            source["file_name"] = resolved.name
            with contextlib.suppress(Exception):
                source["file_hash"] = _file_hash(resolved)
    elif raw_name:
        source["file_name"] = str(raw_name)

    if source:
        source["source_key"] = _stable_json_hash(source)
    return source


def _html_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    match = _HTML_TITLE_RE.search(text)
    return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip()) if match else ""


def _view_model_from_html(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    match = _HTML_BACKFILL_SCRIPT_RE.search(text)
    if not match:
        return None
    payload = html.unescape(match.group(1)).strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _dashboard_entries_from_exports(state: dict[str, Any]) -> list[dict[str, Any]]:
    export_dir = Path(os.environ.get("OPENBENCH_EXPORT_DIR") or "outputs").resolve()
    if not export_dir.exists() or not export_dir.is_dir():
        return []

    existing_paths = set()
    for entry in _state_dashboards(state):
        artifact = entry.get("artifact")
        if isinstance(artifact, dict) and artifact.get("path"):
            existing_paths.add(str(artifact.get("path")))
    entries: list[dict[str, Any]] = []
    for path in sorted(export_dir.glob("*.html"), key=lambda item: item.stat().st_mtime, reverse=True):
        resolved = str(path.resolve())
        if resolved in existing_paths:
            continue
        view_model = _view_model_from_html(path)
        if not view_model:
            continue
        source = _source_signature_from_view_model(view_model)
        template = {"source": "imported", "format": "html", "template_key": _stable_json_hash("html-export")}
        match_key = _stable_json_hash(
            {
                "imported_path": resolved,
                "view_model": view_model,
                "source_key": source.get("source_key"),
            },
            24,
        )
        created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        artifact = _dashboard_artifact_from_view_model(
            view_model,
            path.resolve(),
            source=source,
            created_at=created_at,
        )
        entries.append(
            {
                "id": f"dash_{match_key}",
                "match_key": match_key,
                "title": artifact.get("title"),
                "description": artifact.get("description"),
                "created_at": created_at,
                "updated_at": created_at,
                "source": source,
                "template": template,
                "artifact": artifact,
                "imported": True,
            }
        )
    return entries


def _ensure_export_backfill(state: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = state if isinstance(state, dict) else _load_dashboard_state()
    entries = _dashboard_entries_from_exports(loaded)
    if not entries:
        return loaded
    dashboards = _state_dashboards(loaded)
    known_ids = {str(entry.get("id")) for entry in dashboards}
    for entry in entries:
        if str(entry.get("id")) not in known_ids:
            dashboards.append(entry)
            known_ids.add(str(entry.get("id")))
    dashboards.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    loaded["dashboards"] = dashboards[:_MAX_DASHBOARD_MEMORY_ITEMS]
    _save_dashboard_state(loaded)
    return loaded


def _search_text(entry: dict[str, Any]) -> str:
    summary = _dashboard_summary(entry)
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    template = entry.get("template") if isinstance(entry.get("template"), dict) else {}
    parts = [
        summary.get("title"),
        summary.get("description"),
        summary.get("source_file"),
        summary.get("source_path"),
        summary.get("template_name"),
        template.get("path"),
        source.get("file_hash"),
    ]
    return " ".join(str(part).lower() for part in parts if part)


def _score_dashboard(entry: dict[str, Any], query: str) -> int:
    text = _search_text(entry)
    tokens = [token for token in re.split(r"[^a-z0-9]+", query.lower()) if token]
    if not tokens:
        return 1
    score = 0
    for token in tokens:
        if token in text:
            score += 3
        if token and any(part.startswith(token) for part in text.split()):
            score += 1
    return score


def _source_signature_matches(saved: dict[str, Any], current: dict[str, Any]) -> bool:
    if not current:
        return True
    current_hash = current.get("file_hash")
    saved_hash = saved.get("file_hash")
    if current_hash:
        return saved_hash == current_hash and saved.get("sheet") == current.get("sheet")
    current_schema = current.get("schema_hash")
    if current_schema:
        return saved.get("schema_hash") == current_schema and saved.get("sheet") == current.get("sheet")
    current_key = current.get("source_key")
    return bool(current_key and saved.get("source_key") == current_key)


def _template_signature_matches(saved: dict[str, Any], current: dict[str, Any]) -> bool:
    if not current:
        return True
    current_source = current.get("source")
    saved_source = saved.get("source")
    if current_source == "default":
        return saved_source in {None, "", "default"}
    current_hash = current.get("file_hash")
    if current_hash:
        return saved.get("file_hash") == current_hash
    current_text_hash = current.get("text_hash")
    if current_text_hash:
        return saved.get("text_hash") == current_text_hash
    current_key = current.get("template_key")
    if current_key and saved.get("template_key") == current_key:
        return True
    current_path = current.get("path")
    return bool(current_path and saved.get("path") == current_path)


def _find_matching_dashboard(
    match_key: str,
    *,
    source: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    state = _load_dashboard_state()
    for entry in _state_dashboards(state):
        if entry.get("match_key") == match_key:
            return entry
    if not source:
        return None
    candidates = []
    for entry in _state_dashboards(state):
        saved_source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        saved_template = entry.get("template") if isinstance(entry.get("template"), dict) else {}
        if not _source_signature_matches(saved_source, source):
            continue
        if template and not _template_signature_matches(saved_template, template):
            continue
        candidates.append(entry)
    candidates.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return candidates[0] if candidates else None


def _latest_source_dashboard(source: dict[str, Any]) -> dict[str, Any] | None:
    state = _load_dashboard_state()
    candidates = []
    for entry in _state_dashboards(state):
        saved_source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        if _source_signature_matches(saved_source, source):
            candidates.append(entry)
    candidates.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return candidates[0] if candidates else None


def _artifact_from_memory(entry: dict[str, Any], *, loaded: bool = False) -> dict[str, Any]:
    artifact = copy.deepcopy(entry.get("artifact") if isinstance(entry.get("artifact"), dict) else {})
    if not artifact:
        return {}
    artifact["memory"] = {
        "dashboard_id": entry.get("id"),
        "match_key": entry.get("match_key"),
        "created_at": entry.get("created_at"),
        "loaded": loaded,
        "reused": not loaded,
    }
    return artifact


def _remember_dashboard(
    artifact: dict[str, Any],
    *,
    source: dict[str, Any],
    template: dict[str, Any],
    match_key: str,
) -> dict[str, Any]:
    state = _load_dashboard_state()
    dashboards = _state_dashboards(state)
    dashboard_id = f"dash_{match_key}"
    now = _now_iso()
    existing = next((entry for entry in dashboards if entry.get("id") == dashboard_id), None)
    entry = {
        "id": dashboard_id,
        "match_key": match_key,
        "title": artifact.get("title"),
        "description": artifact.get("description") or artifact.get("summary"),
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
        "source": source,
        "template": template,
        "artifact": copy.deepcopy(artifact),
    }
    dashboards = [item for item in dashboards if item.get("id") != dashboard_id]
    dashboards.insert(0, entry)
    state["dashboards"] = dashboards[:_MAX_DASHBOARD_MEMORY_ITEMS]
    _save_dashboard_state(state)
    return entry


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


def extract_metadata(
    path: str,
    sheet: str | int | None = None,
    sample_rows: int = _SAMPLE_ROWS,
) -> dict[str, Any]:
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
        "dialect": "sqlite",
        "table": str(table_name),
        "datasets": datasets,
        "errors": errors,
    }
    _persist_source_context({"path": str(p.resolve()), "sheet": _json_value(resolved_sheet)})
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
) -> dict[str, Any]:
    """Create a dashboard artifact from a declarative ViewModel."""
    if not isinstance(view_model, dict) or not view_model:
        return _error("dashboard", "`view_model` must be a non-empty object")

    view_model = _hydrate_cached_datasets(view_model)
    state = _load_dashboard_state()
    source_signature = _source_signature(state)
    template_signature = _template_signature(
        template_path=template_path,
        template_text=template_text,
        template_format=template_format,
    )
    match_key = _dashboard_match_key(source_signature, template_signature)
    if not (source_signature.get("file_hash") or source_signature.get("schema_hash")):
        match_key = _stable_json_hash(
            {
                "source_template_key": match_key,
                "view_model": view_model,
            },
            24,
        )
    if source_signature.get("file_hash") or source_signature.get("schema_hash"):
        existing = _find_matching_dashboard(
            match_key,
            source=source_signature,
            template=template_signature,
        )
        if existing:
            item = _artifact_from_memory(existing)
            if item:
                _push_to_render_queue(item)
                return item

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
    entry = _remember_dashboard(
        item,
        source=source_signature,
        template=template_signature,
        match_key=match_key,
    )
    item["memory"] = {
        "dashboard_id": entry.get("id"),
        "match_key": entry.get("match_key"),
        "created_at": entry.get("created_at"),
        "loaded": False,
        "reused": False,
    }
    logger.info(
        "[dashboard] artifact created render_mode=%s template_source=%s template_format=%s "
        "template_name=%s title=%s datasets=%d kpis=%d sections=%d charts=%d tables=%d "
        "warnings=%d",
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
    )
    _push_to_render_queue(item)
    return item


def search_dashboards(
    query: str | None = None,
    source_path: str | None = None,
    template_path: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search persisted dashboard memory by title, data source, template, or prompt text."""
    state = _ensure_export_backfill(_load_dashboard_state())
    dashboards = _state_dashboards(state)
    try:
        max_items = max(1, min(int(limit), 25))
    except Exception:
        max_items = 5

    source_probe: dict[str, Any] = {}
    source_hash = ""
    source_query = ""
    if source_path:
        path = Path(source_path)
        source_query = path.stem.replace("_", " ").replace("-", " ")
        source_probe = _source_signature_from_path(source_path)
        if path.exists():
            with contextlib.suppress(Exception):
                source_hash = _file_hash(path)

    template_probe: dict[str, Any] = {}
    template_hash = ""
    if template_path:
        path = Path(template_path)
        template_probe = _template_signature(template_path=template_path)
        if path.exists():
            with contextlib.suppress(Exception):
                template_hash = _file_hash(path)

    ranked: list[tuple[int, dict[str, Any], bool | None, bool | None]] = []
    for entry in dashboards:
        score = _score_dashboard(entry, query or "")
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        template = entry.get("template") if isinstance(entry.get("template"), dict) else {}
        exact_source = None
        exact_template = None
        if source_path:
            exact_source = _source_signature_matches(source, source_probe)
            haystack = f"{source.get('path', '')} {source.get('file_name', '')}".lower()
            if exact_source:
                score += 20
            elif source_hash and source.get("file_hash") == source_hash:
                score += 15
            elif str(source_path).lower() in haystack:
                score += 10
            elif not source.get("file_hash") and source_query and _score_dashboard(entry, source_query) > 0:
                score += _score_dashboard(entry, source_query)
            else:
                continue
        if template_path:
            exact_template = _template_signature_matches(template, template_probe)
            haystack = f"{template.get('path', '')} {template.get('file_name', '')}".lower()
            if exact_template:
                score += 20
            elif template_hash and template.get("file_hash") == template_hash:
                score += 15
            elif str(template_path).lower() in haystack:
                score += 10
            else:
                continue
        if query and score <= 0:
            continue
        ranked.append((score, entry, exact_source, exact_template))

    ranked.sort(key=lambda item: (item[0], item[1].get("updated_at") or ""), reverse=True)
    selected = ranked[:max_items]
    return {
        "count": len(selected),
        "dashboards": [
            _dashboard_summary(
                entry,
                exact_source_match=exact_source,
                exact_template_match=exact_template,
            )
            for _score, entry, exact_source, exact_template in selected
        ],
    }


def load_dashboard(
    dashboard_id: str | None = None,
    query: str | None = None,
    latest: bool = False,
) -> dict[str, Any]:
    """Load a persisted dashboard artifact and push it back to the chat render queue."""
    state = _ensure_export_backfill(_load_dashboard_state())
    dashboards = _state_dashboards(state)
    if not dashboards:
        return _error("dashboard_memory", "No dashboards have been saved yet")

    entry: dict[str, Any] | None = None
    if dashboard_id:
        entry = next((item for item in dashboards if item.get("id") == dashboard_id), None)
    elif latest or not query or query.lower().strip() in {"last", "latest", "terakhir"}:
        entry = sorted(dashboards, key=lambda item: item.get("updated_at") or "", reverse=True)[0]
    else:
        matches = [
            (_score_dashboard(item, query), item)
            for item in dashboards
            if _score_dashboard(item, query) > 0
        ]
        matches.sort(key=lambda item: (item[0], item[1].get("updated_at") or ""), reverse=True)
        entry = matches[0][1] if matches else None

    if not entry:
        return {
            "error": "Dashboard memory match not found",
            "available": search_dashboards(limit=10).get("dashboards", []),
        }

    artifact = _artifact_from_memory(entry, loaded=True)
    if not artifact:
        return _error("dashboard_memory", "Saved dashboard artifact is empty or invalid")
    _push_to_render_queue(artifact)
    return artifact


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
    "Do not include raw UI code.",
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
    },
    ["view_model"],
)

SEARCH_DASHBOARDS_SCHEMA = _schema(
    "search_dashboards",
    "Search persisted dashboard memory across chat sessions. Use this before "
    "creating or recreating a dashboard from an uploaded CSV/XLSX. If the result "
    "has reusable_match=true, call load_dashboard with that dashboard_id instead "
    "of regenerating unless the user explicitly requested changes.",
    {
        "query": {
            "type": "string",
            "description": "Optional natural-language query such as a dashboard title or data file name.",
        },
        "source_path": {
            "type": "string",
            "description": (
                "Optional CSV/XLSX path to match by file hash, sheet, row count, "
                "column names, and column dtypes."
            ),
        },
        "template_path": {
            "type": "string",
            "description": "Optional dashboard template path to match by file hash or path.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum dashboards to return, default 5.",
        },
    },
    [],
)

LOAD_DASHBOARD_SCHEMA = _schema(
    "load_dashboard",
    "Load a dashboard from persisted dashboard memory and publish the exact saved "
    "artifact back to chat. Use `latest=true` for requests like 'load dashboard "
    "terakhir', or pass `dashboard_id` from search_dashboards.",
    {
        "dashboard_id": {
            "type": "string",
            "description": "Dashboard id returned by search_dashboards.",
        },
        "query": {
            "type": "string",
            "description": "Optional query when the user describes the dashboard/source/template.",
        },
        "latest": {
            "type": "boolean",
            "description": "Load the most recently generated dashboard.",
        },
    },
    [],
)
