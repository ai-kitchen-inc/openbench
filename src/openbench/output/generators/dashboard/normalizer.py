"""Normalize loose dashboard ViewModel dialects into OpenBench's canonical shape."""

from __future__ import annotations

import logging
import re
from typing import Any

from openbench.output.generators.dashboard.datasets import (
    _first_category_key,
    _first_numeric_key,
    _normalize_datasets,
)

logger = logging.getLogger(__name__)

_CHART_TYPES = {
    "chart",
    "bar",
    "bar_chart",
    "column",
    "column_chart",
    "line",
    "line_chart",
    "area",
    "area_chart",
    "pie",
    "pie_chart",
    "scatter",
    "scatter_chart",
}
_KPI_TYPES = {"kpi", "metric", "stat", "stat_card", "metric_card", "kpi_card"}
_TABLE_TYPES = {"table", "data_table"}
_CONTAINER_TYPES = {"section", "group", "container", "row", "column", "columns", "grid"}
_NESTED_PROPERTY_KEYS = ("props", "parameters", "content", "value", "view_model", "options")
_CHILD_KEYS = ("components", "items", "widgets", "panels", "cards", "children", "columns")


def normalize_dashboard_view_model(content: dict[str, Any], *, title: str | None = None) -> dict[str, Any]:
    """Return a deterministic dashboard ViewModel with ``kpis`` and ``sections[].items``.

    The LLM often emits semantically equivalent dashboard JSON in component,
    Chart.js, grid, or prop-oriented dialects. This function accepts those loose
    shapes and returns the canonical shape consumed by the HTML and A2UI renderers.
    """
    datasets = _normalize_dashboard_datasets(content.get("datasets"))
    dialects = _detect_dialects(content)
    kpis: list[dict[str, Any]] = []
    panels: list[dict[str, Any]] = []

    for item in _as_list(content.get("kpis")):
        kpi = _normalize_kpi(item, datasets)
        if kpi:
            kpis.append(kpi)

    top_level_items: list[Any] = []
    for key in ("items", "components", "widgets", "panels", "cards", "charts"):
        top_level_items.extend(_as_list(content.get(key)))
    skip_raw_sections = bool(top_level_items) and (
        _sections_contain_component_containers(content.get("sections"))
        or _sections_have_only_empty_charts(content.get("sections"))
    )
    if not skip_raw_sections:
        for section in _as_list(content.get("sections")):
            normalized_items = _normalize_items(_section_items(section), datasets, kpis)
            if normalized_items:
                panels.extend(normalized_items)

    if _is_visual_item(content):
        top_level_items.append(content)
    panels.extend(_normalize_items(top_level_items, datasets, kpis))
    if not panels and _should_synthesize_panels_from_datasets(datasets):
        panels.extend(_panels_from_datasets(datasets))

    if not kpis:
        for item in _as_list(content.get("metrics")) + _as_list(content.get("stats")):
            kpi = _normalize_kpi(item, datasets)
            if kpi:
                kpis.append(kpi)

    canonical = {
        key: value
        for key, value in content.items()
        if key not in {"components", "items", "widgets", "panels", "cards", "charts"}
    }
    canonical["title"] = str(title or content.get("title") or "OpenBench Dashboard")
    canonical["description"] = str(content.get("description") or "")
    canonical["datasets"] = datasets
    canonical["kpis"] = _dedupe_records(kpis)
    canonical["sections"] = _canonical_sections(content.get("sections"), panels)

    chart_count = sum(
        1
        for section in canonical["sections"]
        for item in section.get("items", [])
        if item.get("type") == "chart"
    )
    table_count = sum(
        1
        for section in canonical["sections"]
        for item in section.get("items", [])
        if item.get("type") == "table"
    )
    unresolved = _unresolved_charts(canonical["sections"])
    if unresolved:
        logger.warning("[dashboard] unresolved chart items after normalization: %s", unresolved)
    logger.info(
        "[dashboard] normalized dialect=%s kpis=%d charts=%d tables=%d unresolved_charts=%d",
        ",".join(dialects) or "canonical",
        len(canonical["kpis"]),
        chart_count,
        table_count,
        len(unresolved),
    )
    return canonical


def _normalize_dashboard_datasets(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(raw, dict):
        normalized: dict[str, list[dict[str, Any]]] = {}
        for key, value in raw.items():
            rows = _records_from_value(value)
            if rows:
                normalized[str(key)] = rows
        return normalized
    return _normalize_datasets(raw)


def _detect_dialects(content: dict[str, Any]) -> list[str]:
    dialects: list[str] = []
    if _has_nonempty_sections(content.get("sections")):
        dialects.append("canonical")
    if isinstance(content.get("components"), list):
        dialects.append("layout_components" if isinstance(content.get("layout"), dict) else "components")
        if any(_is_container(item) for item in _as_list(content.get("components"))):
            dialects.append("section_grid_components")
        if any(_component_kind(item) == "row" for item in _as_list(content.get("components"))):
            dialects.append("row_props")
    if isinstance(content.get("charts"), list):
        dialects.append("charts_list")
    if _looks_like_chartjs_data(content.get("data")):
        dialects.append("chartjs")
    return dialects


def _has_nonempty_sections(value: Any) -> bool:
    return any(_section_items(section) for section in _as_list(value))


def _sections_contain_component_containers(value: Any) -> bool:
    for section in _as_list(value):
        for item in _section_items(section):
            if isinstance(item, dict) and _section_items(item) and _is_container(item):
                return True
    return False


def _sections_have_only_empty_charts(value: Any) -> bool:
    items: list[Any] = []
    for section in _as_list(value):
        items.extend(_section_items(section))
    if not items:
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        if _component_kind(item) not in _CHART_TYPES:
            return False
        if _records_from_value(item.get("data")) or _records_from_value(item.get("records")):
            return False
    return True


def _canonical_sections(raw_sections: Any, panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    title = "Dashboard"
    description = ""
    for section in _as_list(raw_sections):
        if isinstance(section, dict):
            title = str(section.get("title") or title)
            description = str(section.get("description") or description)
            break
    if panels:
        section = {"title": title, "items": _dedupe_records(panels)}
        if description:
            section["description"] = description
        return [section]
    empty_sections: list[dict[str, Any]] = []
    for section in _as_list(raw_sections):
        if not isinstance(section, dict):
            continue
        empty = {"title": str(section.get("title") or "Dashboard"), "items": []}
        if section.get("description"):
            empty["description"] = str(section["description"])
        empty_sections.append(empty)
    return empty_sections


def _normalize_items(
    items: list[Any],
    datasets: dict[str, list[dict[str, Any]]],
    kpis: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _component_kind(item)
        if kind in _CONTAINER_TYPES or (not _is_visual_item(item) and _section_items(item)):
            panels.extend(_normalize_items(_section_items(item), datasets, kpis))
            continue
        if kind == "kpi_grid":
            kpis.extend(_normalize_kpi_grid(item, datasets))
            continue
        if kind in _KPI_TYPES:
            kpi = _normalize_kpi(item, datasets)
            if kpi:
                kpis.append(kpi)
            continue
        if kind in _CHART_TYPES:
            chart = _normalize_chart(item, datasets)
            if chart:
                panels.append(chart)
            continue
        if kind in _TABLE_TYPES:
            table = _normalize_table(item, datasets)
            if table:
                panels.append(table)
    return panels


def _normalize_kpi_grid(item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged = _component_payload(item)
    values = _as_list(_nested_get(merged, "data", "values") or merged.get("values") or merged.get("items"))
    return [kpi for value in values if (kpi := _normalize_kpi(value, datasets))]


def _normalize_kpi(item: Any, datasets: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    merged = _component_payload(item)
    data = merged.get("data") if isinstance(merged.get("data"), dict) else {}
    label = _first_text(merged, data, keys=("label", "title", "name", "metric"))
    value = merged.get("value")
    if value is None and isinstance(data, dict):
        value = data.get("value")
    dataset_key = _dataset_key(merged)
    value_column = _field_value(
        merged,
        (
            "value_column",
            "valueColumn",
            "value_key",
            "valueKey",
            "column",
            "field",
            "value_field",
            "valueField",
        ),
    )
    if value is None and dataset_key and value_column and dataset_key in datasets:
        value = datasets[dataset_key][0].get(value_column) if datasets[dataset_key] else None
    if label is None and value_column:
        label = _titleize(value_column)
    if label is None and value is None:
        return None
    result: dict[str, Any] = {
        "label": label or "KPI",
        "value": value,
    }
    for source_key, target_key in (
        ("format", "format"),
        ("value_format", "value_format"),
        ("valueFormat", "value_format"),
        ("unit", "unit"),
        ("delta", "delta"),
        ("change", "delta"),
        ("description", "description"),
        ("note", "note"),
        ("variant", "variant"),
    ):
        if merged.get(source_key) is not None and result.get(target_key) is None:
            result[target_key] = merged[source_key]
    return result


def _normalize_chart(item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    merged = _with_data_controls(_component_payload(item))
    kind = _component_kind(item)
    chart_type = _chart_type(kind, merged)
    records, chartjs_x, chartjs_y = _chart_records(merged, datasets)
    matched_dataset = ""
    if not records and datasets:
        matched_dataset, matched_records = _match_dataset_for_item(merged, datasets)
        if matched_records:
            records = matched_records
    x_field = _axis_field(
        merged,
        (
            "x_field",
            "xField",
            "x",
            "x_key",
            "xKey",
            "x_axis",
            "xAxis",
            "label_column",
            "labelColumn",
        ),
        ("x", "label_column", "labelColumn"),
    )
    y_field = _axis_field(
        merged,
        (
            "y_field",
            "yField",
            "y",
            "y_key",
            "yKey",
            "y_axis",
            "yAxis",
            "value_field",
            "valueField",
            "value_column",
            "valueColumn",
        ),
        ("y", "value_column", "valueColumn"),
    )
    y_fields = merged.get("y_fields") or merged.get("yFields")
    if not y_field and isinstance(y_fields, list) and y_fields:
        y_field = _field_from_axis(y_fields[0])
    if records:
        if x_field and not _field_exists(records, x_field):
            x_field = ""
        if y_field and not _field_exists(records, y_field):
            y_field = ""
    x_field = x_field or chartjs_x or _first_category_key(records)
    y_field = y_field or chartjs_y or _first_numeric_key(records, fallback=x_field)
    result = {
        "type": "chart",
        "chart_type": chart_type,
        "title": _first_text(merged, keys=("title", "label", "name")) or "Chart",
        "data": records,
        "x_field": x_field,
        "y_field": y_field,
    }
    if merged.get("description"):
        result["description"] = merged["description"]
    dataset_key = _dataset_key(merged) or matched_dataset
    if dataset_key:
        result["dataset"] = dataset_key
    return result


def _normalize_table(item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    merged = _with_data_controls(_component_payload(item))
    records = _resolve_records(merged, datasets)
    result = {
        "type": "table",
        "title": _first_text(merged, keys=("title", "label", "name")) or "Table",
        "data": records,
        "columns": merged.get("columns") or merged.get("fields") or [],
    }
    dataset_key = _dataset_key(merged)
    if dataset_key:
        result["dataset"] = dataset_key
    if merged.get("description"):
        result["description"] = merged["description"]
    return result


def _component_payload(component: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in _NESTED_PROPERTY_KEYS:
        nested = component.get(key)
        if isinstance(nested, dict):
            merged.update(nested)
    for key, value in component.items():
        if key in _NESTED_PROPERTY_KEYS and isinstance(value, dict):
            continue
        if key in {"type", "component", "kind"} and key in merged:
            merged[f"component_{key}"] = value
            continue
        merged[key] = value
    return merged


def _with_data_controls(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    if not isinstance(data, dict) or _looks_like_chartjs_data(data) or _records_from_value(data):
        return item
    merged = dict(item)
    for key, value in data.items():
        if key not in merged:
            merged[key] = value
    if "label" in data and not any(merged.get(key) for key in ("x", "x_field", "xField")):
        merged["x"] = data["label"]
    if "value" in data and not any(merged.get(key) for key in ("y", "y_field", "yField")):
        merged["y"] = data["value"]
    return merged


def _component_kind(component: Any) -> str:
    if not isinstance(component, dict):
        return ""
    merged = _component_payload(component)
    raw = (
        component.get("type")
        or component.get("component")
        or component.get("kind")
        or merged.get("type")
        or merged.get("component")
        or merged.get("kind")
        or ""
    )
    if not raw:
        if any(merged.get(key) is not None for key in ("chart_type", "chartType", "visualization")):
            return "chart"
        if merged.get("columns") is not None and (
            merged.get("data") is not None or _dataset_key(merged)
        ):
            return "table"
    return str(raw).lower()


def _is_visual_item(item: dict[str, Any]) -> bool:
    kind = _component_kind(item)
    return kind in _CHART_TYPES or kind in _KPI_TYPES or kind in _TABLE_TYPES or kind == "kpi_grid"


def _is_container(item: Any) -> bool:
    return isinstance(item, dict) and _component_kind(item) in _CONTAINER_TYPES


def _section_items(section: Any) -> list[Any]:
    if not isinstance(section, dict):
        return []
    children: list[Any] = []
    for key in _CHILD_KEYS:
        value = section.get(key)
        if key == "columns" and not isinstance(value, list):
            continue
        children.extend(_as_list(value))
    return children


def _chart_type(kind: str, merged: dict[str, Any]) -> str:
    requested = str(
        merged.get("chart_type")
        or merged.get("chartType")
        or merged.get("visualization")
        or merged.get("visualizationType")
        or (merged.get("type") if kind == "chart" else None)
        or kind
        or "bar"
    ).lower()
    aliases = {
        "bar_chart": "bar",
        "column": "bar",
        "column_chart": "bar",
        "line_chart": "line",
        "area_chart": "area",
        "pie_chart": "pie",
        "scatter_chart": "scatter",
    }
    return aliases.get(requested, requested.replace("_chart", ""))


def _chart_records(
    merged: dict[str, Any],
    datasets: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    data = merged.get("data")
    if _looks_like_chartjs_data(data):
        return _chartjs_records(data)
    records = _resolve_records(merged, datasets)
    return records, None, None


def _resolve_records(
    item: dict[str, Any],
    datasets: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    for value in (
        item.get("data"),
        item.get("records"),
        item.get("values"),
        item.get("view_data"),
        item.get("viewData"),
    ):
        records = _records_from_value(value)
        if records:
            return records
    dataset_key = _dataset_key(item)
    return datasets.get(dataset_key, []) if dataset_key else []


def _records_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        if _looks_like_chartjs_data(value):
            rows, _x, _y = _chartjs_records(value)
            return rows
        for key in ("values", "records", "rows", "data", "groups"):
            records = _records_from_value(value.get(key))
            if records:
                return records
    return []


def _dataset_key(item: dict[str, Any]) -> str:
    value = (
        item.get("dataset_id")
        or item.get("datasetId")
        or item.get("dataset")
        or item.get("dataKey")
        or item.get("source_dataset")
        or item.get("sourceDataset")
        or item.get("source")
    )
    if isinstance(item.get("data"), str):
        value = item["data"]
    if not value and isinstance(item.get("data"), dict):
        data = item["data"]
        value = data.get("dataset_id") or data.get("datasetId") or data.get("dataset")
    return str(value) if value else ""


def _match_dataset_for_item(
    item: dict[str, Any],
    datasets: dict[str, list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    title = _first_text(item, keys=("title", "label", "name")) or ""
    title_tokens = _match_tokens(title)
    best_id = ""
    best_records: list[dict[str, Any]] = []
    best_score = 0
    for dataset_id, records in datasets.items():
        if not records or _is_kpi_dataset_id(dataset_id):
            continue
        dataset_tokens = _match_tokens(dataset_id)
        for row in records[:3]:
            dataset_tokens.update(_match_tokens(" ".join(str(key) for key in row.keys())))
        score = len(title_tokens & dataset_tokens)
        if score > best_score:
            best_id = dataset_id
            best_records = records
            best_score = score
    if best_score > 0:
        return best_id, best_records
    viable = [
        (dataset_id, records)
        for dataset_id, records in datasets.items()
        if records and not _is_kpi_dataset_id(dataset_id)
    ]
    if len(viable) == 1:
        return viable[0]
    return "", []


def _match_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if len(token) > 1 and token not in {"chart", "sales", "trend", "total"}
    }


def _field_exists(records: list[dict[str, Any]], field: str) -> bool:
    return any(field in row for row in records[:10])


def _panels_from_datasets(datasets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    for dataset_id, records in datasets.items():
        if not records or _is_kpi_dataset_id(dataset_id):
            continue
        x_field = _first_category_key(records)
        y_field = _first_numeric_key(records, fallback=x_field)
        if not x_field or not y_field or x_field == y_field:
            continue
        panels.append(
            {
                "type": "chart",
                "chart_type": "line" if _looks_time_like_field(x_field) else "bar",
                "title": _titleize(dataset_id),
                "data": records,
                "dataset": dataset_id,
                "x_field": x_field,
                "y_field": y_field,
            }
        )
        if len(panels) >= 4:
            break
    return panels


def _should_synthesize_panels_from_datasets(datasets: dict[str, list[dict[str, Any]]]) -> bool:
    viable = 0
    for dataset_id, records in datasets.items():
        if not records or _is_kpi_dataset_id(dataset_id):
            continue
        x_field = _first_category_key(records)
        y_field = _first_numeric_key(records, fallback=x_field)
        if x_field and y_field and x_field != y_field:
            viable += 1
        if viable >= 2:
            return True
    return False


def _is_kpi_dataset_id(dataset_id: str) -> bool:
    return dataset_id.lower() in {"kpis", "kpi", "metrics", "stats"}


def _looks_time_like_field(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("date", "month", "year", "week", "day", "time"))


def _axis_field(item: dict[str, Any], keys: tuple[str, ...], option_keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _field_from_axis(item.get(key))
        if value:
            return value
    options = item.get("options")
    if isinstance(options, dict):
        for key in option_keys:
            value = _field_from_axis(options.get(key))
            if value:
                return value
    return ""


def _field_value(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _field_from_axis(item.get(key))
        if value:
            return value
    options = item.get("options")
    if isinstance(options, dict):
        for key in keys:
            value = _field_from_axis(options.get(key))
            if value:
                return value
    return ""


def _field_from_axis(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("property", "field", "key", "dataKey", "name", "id", "value", "column"):
            if value.get(key) is not None:
                return str(value[key])
    return ""


def _looks_like_chartjs_data(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("labels"), list)
        and (
            isinstance(value.get("datasets"), list)
            or isinstance(value.get("values"), list)
        )
    )


def _chartjs_records(value: Any) -> tuple[list[dict[str, Any]], str, str]:
    if not _looks_like_chartjs_data(value):
        return [], "label", "value"
    labels = value.get("labels") or []
    if isinstance(value.get("values"), list) and not isinstance(value.get("datasets"), list):
        values = value["values"]
        rows = [
            {"label": label, "value": values[index] if index < len(values) else None}
            for index, label in enumerate(labels)
        ]
        return rows, "label", "value"
    datasets = [dataset for dataset in value.get("datasets") or [] if isinstance(dataset, dict)]
    if not datasets:
        return [], "label", "value"
    keys = [_safe_field_name(str(dataset.get("label") or f"value_{idx + 1}")) for idx, dataset in enumerate(datasets)]
    rows: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        row: dict[str, Any] = {"label": label}
        for key, dataset in zip(keys, datasets, strict=False):
            values = dataset.get("data") if isinstance(dataset.get("data"), list) else []
            row[key] = values[index] if index < len(values) else None
        rows.append(row)
    return rows, "label", keys[0] if keys else "value"


def _first_text(*records: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            value = record.get(key)
            if isinstance(value, (str, int, float, bool)) and str(value):
                return str(value)
    return None


def _nested_get(record: dict[str, Any], *keys: str) -> Any:
    value: Any = record
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        marker = repr(sorted(record.items()))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(record)
    return deduped


def _unresolved_charts(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unresolved: list[dict[str, Any]] = []
    for section in sections:
        for item in section.get("items", []):
            if item.get("type") != "chart":
                continue
            records = _records_from_value(item.get("data"))
            if not records:
                unresolved.append(
                    {
                        "title": item.get("title"),
                        "dataset": item.get("dataset"),
                        "reason": "missing data",
                    }
                )
                continue
            x_field = str(item.get("x_field") or "")
            y_field = str(item.get("y_field") or "")
            if x_field and all(x_field not in row for row in records):
                unresolved.append(
                    {
                        "title": item.get("title"),
                        "dataset": item.get("dataset"),
                        "reason": f"missing x_field {x_field!r}",
                    }
                )
            if y_field and all(y_field not in row for row in records):
                unresolved.append(
                    {
                        "title": item.get("title"),
                        "dataset": item.get("dataset"),
                        "reason": f"missing y_field {y_field!r}",
                    }
                )
    return unresolved


def _safe_field_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip().lower()).strip("_")
    return text or "value"


def _titleize(value: str) -> str:
    return value.replace("_", " ").strip().title()
