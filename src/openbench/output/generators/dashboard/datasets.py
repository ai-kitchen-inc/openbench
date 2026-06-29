"""Dataset normalization, KPI resolution, and column inference helpers.

These functions turn the loose ViewModel dialects (inline data, dataset
references, heterogeneous column specs) into the normalized shapes the
generator and chart renderers consume.
"""

from __future__ import annotations

import math
from typing import Any

from openbench.output.generators.dashboard.formatting import _format_value


def _resolve_kpi_value(item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]) -> Any:
    """Resolve a KPI's value from an inline ``value`` or a dataset column.

    Supports the dataset-backed dialect ``{dataset_id, value_column}`` where the
    number lives in ``datasets[dataset_id][0][value_column]``.
    """
    if item.get("value") is not None:
        return item.get("value")
    dataset_key = item.get("dataset_id") or item.get("dataset") or item.get("source")
    column = (
        item.get("value_column") or item.get("value_key") or item.get("column") or item.get("field")
    )
    if dataset_key and column:
        records = datasets.get(str(dataset_key)) or []
        if records and isinstance(records[0], dict):
            return records[0].get(str(column))
    return None


def _format_kpi_value(item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]) -> str:
    """Format a KPI value, honoring a light ``format`` hint (e.g. ``$#,###.00``)."""
    raw = _resolve_kpi_value(item, datasets)
    text = _format_value(raw)
    if not text:
        return ""
    fmt = str(item.get("format") or "")
    if "$" in fmt and not text.startswith("$"):
        return f"${text}"
    if "%" in fmt and not text.endswith("%"):
        return f"{text}%"
    return text


def _column_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _normalize_table_columns(
    raw_columns: Any,
    records: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    columns = raw_columns if isinstance(raw_columns, list) and raw_columns else []
    if not columns and records:
        columns = list(records[0].keys())

    normalized: list[tuple[str, str]] = []
    for column in columns:
        if isinstance(column, dict):
            key = _column_text(
                column.get("key")
                or column.get("field")
                or column.get("id")
                or column.get("name")
                or column.get("accessor")
                or column.get("dataKey")
                or column.get("value")
            )
            label = _column_text(
                column.get("label")
                or column.get("header")
                or column.get("title")
                or column.get("name")
                or column.get("key")
                or column.get("field")
            )
            resolved_key = key or label
            if resolved_key:
                normalized.append((resolved_key, label or resolved_key))
            continue
        text = _column_text(column)
        if text:
            normalized.append((text, text))
    return normalized


def _table_cell_value(row: dict[str, Any], key: str, label: str) -> Any:
    if key in row:
        return row.get(key)
    if label in row:
        return row.get(label)
    return None


def _normalize_datasets(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(raw, dict):
        result: dict[str, list[dict[str, Any]]] = {}
        for key, value in raw.items():
            if isinstance(value, list):
                result[str(key)] = [row for row in value if isinstance(row, dict)]
        return result
    if isinstance(raw, list):
        result = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            dataset_id = item.get("id") or item.get("name")
            records = item.get("records") or item.get("data") or item.get("groups")
            if dataset_id and isinstance(records, list):
                result[str(dataset_id)] = [row for row in records if isinstance(row, dict)]
        return result
    return {}


def _first_key(records: list[dict[str, Any]]) -> str:
    if not records:
        return "name"
    return str(next(iter(records[0].keys()), "name"))


def _first_category_key(records: list[dict[str, Any]]) -> str:
    """First non-numeric column — the natural x-axis / label.

    Widgets often omit ``x_axis``; picking the first *category* column (rather
    than the first column) keeps a leading numeric measure from being used as
    the x-axis.
    """
    if not records:
        return "name"
    keys = list(records[0].keys())
    for key in keys:
        value = _first_non_null(records, key)
        if value is not None and _number(value) is None:
            return str(key)
    return str(keys[0]) if keys else "name"


def _first_non_null(records: list[dict[str, Any]], key: str) -> Any:
    for row in records:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _first_numeric_key(records: list[dict[str, Any]], *, fallback: str = "") -> str:
    first_numeric: str | None = None
    for row in records:
        for key, value in row.items():
            if _number(value) is None:
                continue
            if first_numeric is None:
                first_numeric = str(key)
            if str(key) != fallback:
                return str(key)
    return first_numeric or "value"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.replace(",", ""))
        except ValueError:
            return None
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    return None
