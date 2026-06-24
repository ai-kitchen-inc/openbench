"""Convert an OpenBench dashboard ViewModel to a Grafana dashboard model.

The output is a self-contained Grafana dashboard JSON: every panel carries its
own data inline via the built-in ``grafana-testdata-datasource`` ``csv_content``
scenario, so importing the file into any Grafana needs no external data source.

The conversion mirrors the field-alias resolution used by the on-screen renderers
(``DashboardGenerator`` and the React ``ObDashboardFrame``) so the exported
dashboard matches what the user sees.
"""

from __future__ import annotations

from typing import Any

# Built-in datasource shipped with every Grafana install.
_TESTDATA_PLUGIN = "grafana-testdata-datasource"
_DS_INPUT = "${DS_TESTDATA}"

# 24-column Grafana grid layout.
_GRID_COLS = 24
_KPI_W = 6
_KPI_H = 4
_PANEL_W = 12
_PANEL_H = 8


def view_model_to_grafana(view_model: dict[str, Any]) -> dict[str, Any]:
    """Convert a dashboard ViewModel to an importable Grafana dashboard model.

    Args:
        view_model: OpenBench dashboard ViewModel (``title``, ``description``,
            ``datasets``, ``kpis``, ``sections``).

    Returns:
        A Grafana dashboard dict ready to serialize to JSON and import.
    """
    view_model = view_model or {}
    datasets = _normalize_datasets(view_model.get("datasets"))
    title = str(view_model.get("title") or "OpenBench Dashboard")

    panels: list[dict[str, Any]] = []
    cursor = _GridCursor()
    panel_id = _Counter()

    for kpi in view_model.get("kpis") or []:
        if isinstance(kpi, dict):
            panels.append(_kpi_panel(kpi, panel_id.next(), cursor))

    for section in view_model.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or "")
        items = section.get("items") or section.get("components") or []
        if section_title:
            cursor.newline()
            panels.append(_row_panel(section_title, panel_id.next(), cursor))
        for item in items:
            if not isinstance(item, dict):
                continue
            panel = _item_panel(item, datasets, panel_id.next(), cursor)
            if panel is not None:
                panels.append(panel)

    return {
        "__inputs": [
            {
                "name": "DS_TESTDATA",
                "label": "TestData",
                "description": "",
                "type": "datasource",
                "pluginId": _TESTDATA_PLUGIN,
                "pluginName": "TestData",
            }
        ],
        "__requires": [
            {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.0.0"},
            {
                "type": "datasource",
                "id": _TESTDATA_PLUGIN,
                "name": "TestData",
                "version": "1.0.0",
            },
        ],
        "annotations": {"list": []},
        "editable": True,
        "description": str(view_model.get("description") or ""),
        "panels": panels,
        "schemaVersion": 39,
        "tags": ["openbench"],
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": title,
        "uid": None,
        "version": 1,
    }


class _Counter:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


class _GridCursor:
    """Tracks x/y placement across a 24-column Grafana grid."""

    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self._row_h = 0

    def place(self, w: int, h: int) -> dict[str, int]:
        if self.x + w > _GRID_COLS:
            self.newline()
        pos = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.x += w
        self._row_h = max(self._row_h, h)
        return pos

    def newline(self) -> None:
        if self.x == 0 and self._row_h == 0:
            return
        self.y += self._row_h or _PANEL_H
        self.x = 0
        self._row_h = 0


def _datasource_ref() -> dict[str, str]:
    return {"type": _TESTDATA_PLUGIN, "uid": _DS_INPUT}


def _csv_target(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "refId": "A",
        "datasource": _datasource_ref(),
        "scenarioId": "csv_content",
        "csvContent": _records_to_csv(records),
    }


def _row_panel(title: str, panel_id: int, cursor: _GridCursor) -> dict[str, Any]:
    pos = {"h": 1, "w": _GRID_COLS, "x": 0, "y": cursor.y}
    cursor.y += 1
    return {
        "id": panel_id,
        "type": "row",
        "title": title,
        "gridPos": pos,
        "collapsed": False,
        "panels": [],
    }


def _kpi_panel(kpi: dict[str, Any], panel_id: int, cursor: _GridCursor) -> dict[str, Any]:
    label = str(kpi.get("label") or kpi.get("title") or "KPI")
    value = kpi.get("value")
    unit = str(kpi.get("unit") or "")
    records = [{"metric": label, "value": value}]
    return {
        "id": panel_id,
        "type": "stat",
        "title": label,
        "gridPos": cursor.place(_KPI_W, _KPI_H),
        "datasource": _datasource_ref(),
        "targets": [_csv_target(records)],
        "fieldConfig": {"defaults": {"unit": unit or "none"}, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "/^value$/", "values": False},
            "textMode": "value_and_name",
            "colorMode": "none",
            "graphMode": "none",
        },
    }


def _item_panel(
    item: dict[str, Any],
    datasets: dict[str, list[dict[str, Any]]],
    panel_id: int,
    cursor: _GridCursor,
) -> dict[str, Any] | None:
    kind = str(item.get("type") or item.get("kind") or "chart").lower()
    if kind in {"chart", "bar", "line", "area", "pie", "scatter"}:
        return _chart_panel(item, datasets, panel_id, cursor)
    if kind == "table":
        return _table_panel(item, datasets, panel_id, cursor)
    if kind in {"text", "markdown", "summary"}:
        return _text_panel(item, panel_id, cursor)
    if kind in {"kpi", "metric"}:
        return _kpi_panel(item, panel_id, cursor)
    return _text_panel(item, panel_id, cursor)


# Map an OpenBench chart type to a Grafana panel type.
_CHART_PANEL_TYPE = {
    "bar": "barchart",
    "line": "timeseries",
    "area": "timeseries",
    "pie": "piechart",
    "scatter": "xychart",
}


def _chart_panel(
    item: dict[str, Any],
    datasets: dict[str, list[dict[str, Any]]],
    panel_id: int,
    cursor: _GridCursor,
) -> dict[str, Any]:
    records = _resolve_item_data(item, datasets)
    chart_type = str(
        item.get("chart_type") or item.get("chartType") or item.get("visualization") or item.get("type") or "bar"
    ).lower()
    panel_type = _CHART_PANEL_TYPE.get(chart_type, "barchart")
    x_key = str(
        item.get("x") or item.get("x_key") or item.get("xKey") or item.get("xField") or _first_key(records)
    )
    y_keys = _series_keys(item, records, x_key)

    options: dict[str, Any] = {"legend": {"showLegend": True}}
    if panel_type == "barchart":
        options["xField"] = x_key
    if panel_type == "piechart":
        options["reduceOptions"] = {"calcs": ["lastNotNull"], "fields": "", "values": True}

    return {
        "id": panel_id,
        "type": panel_type,
        "title": str(item.get("title") or "Chart"),
        "description": str(item.get("description") or ""),
        "gridPos": cursor.place(_PANEL_W, _PANEL_H),
        "datasource": _datasource_ref(),
        "targets": [_csv_target(_project_records(records, [x_key, *y_keys]))],
        "fieldConfig": {"defaults": {"custom": {}}, "overrides": []},
        "options": options,
    }


def _table_panel(
    item: dict[str, Any],
    datasets: dict[str, list[dict[str, Any]]],
    panel_id: int,
    cursor: _GridCursor,
) -> dict[str, Any]:
    records = _resolve_item_data(item, datasets)
    columns = _normalize_table_columns(item.get("columns"), records)
    keys = [key for key, _label in columns] or (list(records[0].keys()) if records else [])
    return {
        "id": panel_id,
        "type": "table",
        "title": str(item.get("title") or "Table"),
        "gridPos": cursor.place(_PANEL_W, _PANEL_H),
        "datasource": _datasource_ref(),
        "targets": [_csv_target(_project_records(records, keys))],
        "fieldConfig": {"defaults": {"custom": {}}, "overrides": []},
        "options": {"showHeader": True},
    }


def _text_panel(item: dict[str, Any], panel_id: int, cursor: _GridCursor) -> dict[str, Any]:
    content = str(item.get("content") or item.get("text") or item.get("value") or "")
    return {
        "id": panel_id,
        "type": "text",
        "title": str(item.get("title") or "Summary"),
        "gridPos": cursor.place(_PANEL_W, _PANEL_H),
        "options": {"mode": "markdown", "content": content},
    }


# --- ViewModel resolution helpers (mirror DashboardGenerator) -----------------


def _resolve_item_data(
    item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    data = item.get("data") or item.get("records")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    dataset_key = (
        item.get("dataset")
        or item.get("dataset_id")
        or item.get("datasetId")
        or item.get("source")
    )
    if dataset_key and str(dataset_key) in datasets:
        return datasets[str(dataset_key)]
    return []


def _series_keys(item: dict[str, Any], records: list[dict[str, Any]], x_key: str) -> list[str]:
    raw = (
        item.get("series")
        or item.get("y")
        or item.get("y_key")
        or item.get("yKey")
        or item.get("metric")
        or item.get("value")
    )
    if isinstance(raw, list):
        keys = [str(k) for k in raw if k]
        if keys:
            return keys
    if isinstance(raw, str) and raw:
        return [raw]
    return [_first_numeric_key(records, fallback=x_key)]


def _normalize_table_columns(
    raw_columns: Any, records: list[dict[str, Any]]
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
            resolved = key or label
            if resolved:
                normalized.append((resolved, label or resolved))
            continue
        text = _column_text(column)
        if text:
            normalized.append((text, text))
    return normalized


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


def _column_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _first_key(records: list[dict[str, Any]]) -> str:
    if not records:
        return "name"
    return str(next(iter(records[0].keys()), "name"))


def _first_numeric_key(records: list[dict[str, Any]], *, fallback: str = "") -> str:
    for row in records:
        for key, value in row.items():
            if key == fallback:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(key)
            if isinstance(value, str):
                try:
                    float(value.replace(",", ""))
                    return str(key)
                except ValueError:
                    continue
    return "value"


# --- CSV serialization --------------------------------------------------------


def _project_records(
    records: list[dict[str, Any]], keys: list[str]
) -> list[dict[str, Any]]:
    seen: list[str] = []
    for key in keys:
        if key and key not in seen:
            seen.append(key)
    if not seen:
        return records
    return [{key: row.get(key) for key in seen} for row in records]


def _records_to_csv(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    headers: list[str] = []
    for row in records:
        for key in row.keys():
            if key not in headers:
                headers.append(str(key))
    lines = [",".join(_csv_field(h) for h in headers)]
    for row in records:
        lines.append(",".join(_csv_field(row.get(h)) for h in headers))
    return "\n".join(lines)


def _csv_field(value: Any) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    else:
        text = str(value)
    if any(ch in text for ch in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text
