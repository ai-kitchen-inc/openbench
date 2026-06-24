"""Dashboard artifact generation from declarative OpenBench ViewModels."""

from __future__ import annotations

import html
import json
import logging
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from openbench.core.abstractions import GeneratedOutput, OutputGenerator

logger = logging.getLogger(__name__)


class DashboardGenerator(OutputGenerator):
    """
    Generate dashboard artifacts from a declarative ViewModel.

    Implements the OutputGenerator interface for dashboard output.
    The primary rendering contract is the returned ``metadata["viewModel"]``
    for A2UI clients. A legacy HTML file is still written as an export/fallback.

    Example:
        >>> generator = DashboardGenerator()
        >>> result = generator.generate(
        ...     content={
        ...         "title": "Sales Dashboard",
        ...         "kpis": [{"label": "Revenue", "value": 1200}],
        ...         "sections": [
        ...             {
        ...                 "title": "Breakdown",
        ...                 "items": [
        ...                     {
        ...                         "type": "chart",
        ...                         "chart_type": "bar",
        ...                         "title": "Revenue by Region",
        ...                         "data": [{"region": "EU", "revenue": 1200}],
        ...                         "x": "region",
        ...                         "y": "revenue",
        ...                     }
        ...                 ],
        ...             }
        ...         ],
        ...     },
        ...     output_path="dashboard.html",
        ... )
    """

    def __init__(self, template: str = "openbench"):
        """
        Initialize dashboard generator.

        Args:
            template: Visual template. Currently ``"openbench"``.
        """
        self.template = template
        logger.debug("DashboardGenerator initialized (template: %s)", template)

    @property
    def output_format(self) -> str:
        """Output format identifier."""
        return "dashboard"

    def validate(self, content: Any) -> bool:
        """
        Validate that content can be rendered as dashboard.

        Args:
            content: Content to validate

        Returns:
            True if content is valid dashboard data
        """
        return isinstance(content, dict) and bool(content)

    def generate(
        self,
        content: Any,
        template: str | None = None,
        output_path: str | None = None,
        title: str | None = None,
        **options,
    ) -> GeneratedOutput:
        """
        Generate a dashboard artifact from a declarative ViewModel.

        Args:
            content: Dashboard ViewModel. See ``docs/DASHBOARD_GENERATOR.md``.
            template: Dashboard template/layout
            output_path: Optional legacy HTML export path. Defaults to
                ``dashboard-<id>.html``.
            title: Optional title override.
            **options: Additional dashboard-specific options

        Returns:
            GeneratedOutput with fallback file path and dashboard ViewModel metadata.
        """
        if not self.validate(content):
            raise ValueError("DashboardGenerator requires a non-empty ViewModel dict.")

        view_model = self._normalize_view_model(content, title=title)
        html_text = self._render_html(view_model, template or self.template)
        out_path = self._resolve_output_path(output_path, view_model)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_text, encoding="utf-8")
        size_bytes = out_path.stat().st_size
        public_url = options.get("public_url")

        return GeneratedOutput(
            file_path=str(out_path),
            format=self.output_format,
            size_bytes=size_bytes,
            metadata={
                "type": "dashboard",
                "title": view_model["title"],
                "description": view_model.get("description", ""),
                "viewModel": view_model,
                "datasets": view_model.get("datasets", {}),
                "kpis": view_model.get("kpis", []),
                "sections": view_model.get("sections", []),
                "template": template or self.template,
                "dashboard_url": public_url,
                "dashboardUrl": public_url,
                "url": public_url,
                "section_count": len(view_model.get("sections", [])),
                "kpi_count": len(view_model.get("kpis", [])),
                "render_mode": "a2ui",
                "legacy_html": True,
                **options,
            },
        )

    def _resolve_output_path(self, output_path: str | None, view_model: dict[str, Any]) -> Path:
        if output_path:
            path = Path(output_path)
        else:
            slug = _slugify(str(view_model.get("title") or "dashboard"))
            path = Path(f"{slug}-{uuid.uuid4().hex[:8]}.html")
        if path.suffix.lower() not in {".html", ".htm"}:
            path = path.with_suffix(".html")
        return path.resolve()

    def _normalize_view_model(
        self, content: dict[str, Any], *, title: str | None = None
    ) -> dict[str, Any]:
        view_model = dict(content)
        view_model["title"] = str(title or view_model.get("title") or "OpenBench Dashboard")
        view_model["description"] = str(view_model.get("description") or "")
        view_model["datasets"] = _normalize_datasets(view_model.get("datasets"))
        view_model["kpis"] = list(view_model.get("kpis") or [])
        sections = view_model.get("sections")
        if not isinstance(sections, list) or not sections:
            sections = [{"title": "Dashboard", "items": list(view_model.get("items") or [])}]
        view_model["sections"] = sections
        return view_model

    def _render_html(self, view_model: dict[str, Any], template: str) -> str:
        title = _escape(str(view_model.get("title") or "OpenBench Dashboard"))
        description = _escape(str(view_model.get("description") or ""))
        body_parts = [
            self._render_header(title, description),
            self._render_kpis(view_model.get("kpis") or []),
            self._render_sections(view_model),
        ]
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        data_json = _escape(json.dumps(view_model, default=str, ensure_ascii=False))
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
{_DASHBOARD_CSS}
  </style>
</head>
<body data-template="{_escape(template)}">
  <main class="ob-dashboard">
    {"".join(body_parts)}
    <footer class="ob-footer">Generated by OpenBench on {generated_at}</footer>
  </main>
  <script type="application/json" id="openbench-dashboard-view-model">{data_json}</script>
</body>
</html>
"""

    @staticmethod
    def _render_header(title: str, description: str) -> str:
        desc_html = f'<p class="ob-dashboard__description">{description}</p>' if description else ""
        return (
            '<header class="ob-dashboard__header">'
            '<div class="ob-dashboard__eyebrow">OpenBench Dashboard</div>'
            f"<h1>{title}</h1>{desc_html}</header>"
        )

    def _render_kpis(self, kpis: list[Any]) -> str:
        cards: list[str] = []
        for item in kpis:
            if not isinstance(item, dict):
                continue
            label = _escape(str(item.get("label") or item.get("title") or "KPI"))
            value = _escape(_format_value(item.get("value")))
            unit = _escape(str(item.get("unit") or ""))
            delta = _escape(str(item.get("delta") or item.get("change") or ""))
            note = _escape(str(item.get("description") or item.get("note") or ""))
            delta_html = f'<span class="ob-kpi__delta">{delta}</span>' if delta else ""
            note_html = f'<div class="ob-kpi__note">{note}</div>' if note else ""
            cards.append(
                '<article class="ob-kpi">'
                f'<div class="ob-kpi__label">{label}</div>'
                f'<div class="ob-kpi__value">{value}<span>{unit}</span></div>'
                f"{delta_html}{note_html}</article>"
            )
        if not cards:
            return ""
        return f'<section class="ob-kpi-grid">{"".join(cards)}</section>'

    def _render_sections(self, view_model: dict[str, Any]) -> str:
        datasets = view_model.get("datasets") or {}
        sections_html: list[str] = []
        for idx, section in enumerate(view_model.get("sections") or []):
            if not isinstance(section, dict):
                continue
            title = _escape(str(section.get("title") or f"Section {idx + 1}"))
            description = _escape(str(section.get("description") or ""))
            items = section.get("items") or section.get("components") or []
            desc_html = f'<p class="ob-section__description">{description}</p>' if description else ""
            panel_html = "".join(
                self._render_item(item, datasets) for item in items if isinstance(item, dict)
            )
            if not panel_html:
                continue
            sections_html.append(
                '<section class="ob-section">'
                f'<div class="ob-section__heading"><h2>{title}</h2>{desc_html}</div>'
                f'<div class="ob-panel-grid">{panel_html}</div></section>'
            )
        return "".join(sections_html)

    def _render_item(self, item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]) -> str:
        item_type = str(item.get("type") or item.get("kind") or "chart").lower()
        if item_type in {"chart", "bar", "line", "area", "pie", "scatter"}:
            return self._render_chart_panel(item, datasets)
        if item_type == "table":
            return self._render_table_panel(item, datasets)
        if item_type in {"text", "markdown", "summary"}:
            return self._render_text_panel(item)
        if item_type in {"kpi", "metric"}:
            return self._render_kpis([item])
        return self._render_text_panel(item)

    def _resolve_item_data(
        self, item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        data = item.get("data") or item.get("records")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        dataset_key = item.get("dataset") or item.get("dataset_id") or item.get("source")
        if dataset_key and str(dataset_key) in datasets:
            return datasets[str(dataset_key)]
        return []

    def _render_chart_panel(
        self, item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]
    ) -> str:
        title = _escape(str(item.get("title") or "Chart"))
        description = _escape(str(item.get("description") or ""))
        chart_type = str(item.get("chart_type") or item.get("chartType") or item.get("type") or "bar")
        records = self._resolve_item_data(item, datasets)
        x_key = str(item.get("x") or item.get("x_key") or item.get("xKey") or _first_key(records))
        y_key = str(
            item.get("y")
            or item.get("y_key")
            or item.get("yKey")
            or _first_numeric_key(records, fallback=x_key)
        )
        desc_html = f'<p class="ob-panel__description">{description}</p>' if description else ""
        chart_html = _render_chart_svg(chart_type, records, x_key=x_key, y_key=y_key)
        return (
            '<article class="ob-panel ob-panel--chart">'
            f'<div class="ob-panel__header"><h3>{title}</h3>{desc_html}</div>'
            f"{chart_html}</article>"
        )

    def _render_table_panel(
        self, item: dict[str, Any], datasets: dict[str, list[dict[str, Any]]]
    ) -> str:
        title = _escape(str(item.get("title") or "Table"))
        records = self._resolve_item_data(item, datasets)
        columns = _normalize_table_columns(item.get("columns"), records)
        header = "".join(f"<th>{_escape(label)}</th>" for key, label in columns)
        rows: list[str] = []
        max_rows = int(item.get("max_rows") or item.get("maxRows") or 20)
        for row in records[:max_rows]:
            cells = "".join(
                f"<td>{_escape(_format_value(_table_cell_value(row, key, label)))}</td>"
                for key, label in columns
            )
            rows.append(f"<tr>{cells}</tr>")
        table = (
            '<div class="ob-table-wrap"><table>'
            f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"
            "</table></div>"
        )
        return f'<article class="ob-panel ob-panel--table"><h3>{title}</h3>{table}</article>'

    @staticmethod
    def _render_text_panel(item: dict[str, Any]) -> str:
        title = _escape(str(item.get("title") or "Summary"))
        content = _escape(str(item.get("content") or item.get("text") or item.get("value") or ""))
        return (
            '<article class="ob-panel ob-panel--text">'
            f"<h3>{title}</h3><p>{content}</p></article>"
        )


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:48] or "dashboard"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        if abs(value) >= 1000:
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}" if abs(value) >= 1000 else str(value)
    if isinstance(value, list):
        return ", ".join(filter(None, (_format_value(item) for item in value)))
    if isinstance(value, dict):
        for key in ("value", "label", "name", "title"):
            if key in value:
                return _format_value(value.get(key))
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


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


def _first_numeric_key(records: list[dict[str, Any]], *, fallback: str = "") -> str:
    for row in records:
        for key, value in row.items():
            if key == fallback:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(key)
            if isinstance(value, str):
                try:
                    float(value)
                    return str(key)
                except ValueError:
                    continue
    return "value"


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


def _chart_points(
    records: list[dict[str, Any]], x_key: str, y_key: str
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for idx, row in enumerate(records):
        y = _number(row.get(y_key))
        if y is None:
            continue
        label = str(row.get(x_key) if row.get(x_key) is not None else idx + 1)
        points.append((label, y))
    return points[:24]


def _render_chart_svg(
    chart_type: str, records: list[dict[str, Any]], *, x_key: str, y_key: str
) -> str:
    points = _chart_points(records, x_key, y_key)
    if not points:
        return '<div class="ob-empty">No chart data available.</div>'
    normalized = chart_type.lower()
    if normalized == "line":
        return _render_line_svg(points, area=False)
    if normalized == "area":
        return _render_line_svg(points, area=True)
    if normalized == "pie":
        return _render_pie_svg(points)
    if normalized == "scatter":
        return _render_scatter_svg(points)
    return _render_bar_svg(points)


def _render_bar_svg(points: list[tuple[str, float]]) -> str:
    width = 720
    height = 300
    left = 42
    bottom = 44
    top = 18
    right = 16
    chart_w = width - left - right
    chart_h = height - top - bottom
    max_val = max([abs(v) for _, v in points] + [1])
    gap = 8
    bar_w = max(8, (chart_w - gap * (len(points) - 1)) / max(len(points), 1))
    bars: list[str] = []
    labels: list[str] = []
    for idx, (label, value) in enumerate(points):
        x = left + idx * (bar_w + gap)
        h = abs(value) / max_val * chart_h
        y = top + chart_h - h
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" rx="3" />'
        )
        labels.append(
            f'<text x="{x + bar_w / 2:.2f}" y="{height - 18}" text-anchor="middle">'
            f"{_escape(_short_label(label))}</text>"
        )
    axis = (
        f'<line x1="{left}" y1="{top + chart_h}" x2="{width - right}" y2="{top + chart_h}" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" />'
        f'<text x="{left - 8}" y="{top + 10}" text-anchor="end">{_escape(_format_value(max_val))}</text>'
    )
    return _svg(width, height, axis + "".join(bars) + "".join(labels), "bar")


def _render_line_svg(points: list[tuple[str, float]], *, area: bool) -> str:
    width = 720
    height = 300
    left = 42
    bottom = 42
    top = 18
    right = 18
    chart_w = width - left - right
    chart_h = height - top - bottom
    values = [v for _, v in points]
    min_val = min(values + [0])
    max_val = max(values + [1])
    span = max(max_val - min_val, 1)
    coords: list[tuple[float, float]] = []
    for idx, (_, value) in enumerate(points):
        x = left + (idx / max(len(points) - 1, 1)) * chart_w
        y = top + (max_val - value) / span * chart_h
        coords.append((x, y))
    path_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    axis_y = top + chart_h
    axis = (
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{axis_y}" />'
    )
    fill = ""
    if area and coords:
        first_x, _ = coords[0]
        last_x, _ = coords[-1]
        fill = (
            f'<polygon class="area" points="{first_x:.2f},{axis_y:.2f} '
            f'{path_points} {last_x:.2f},{axis_y:.2f}" />'
        )
    circles = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" />' for x, y in coords)
    labels = "".join(
        f'<text x="{x:.2f}" y="{height - 16}" text-anchor="middle">{_escape(_short_label(label))}</text>'
        for (label, _), (x, _y) in zip(points[:: max(1, len(points) // 6)], coords[:: max(1, len(points) // 6)], strict=False)
    )
    return _svg(
        width,
        height,
        axis + fill + f'<polyline points="{path_points}" />' + circles + labels,
        "line",
    )


def _render_scatter_svg(points: list[tuple[str, float]]) -> str:
    width = 720
    height = 300
    left = 42
    bottom = 42
    top = 18
    right = 18
    chart_w = width - left - right
    chart_h = height - top - bottom
    values = [value for _, value in points]
    max_val = max(values + [1])
    min_val = min(values + [0])
    span = max(max_val - min_val, 1)
    circles: list[str] = []
    for idx, (_label, value) in enumerate(points):
        x = left + (idx / max(len(points) - 1, 1)) * chart_w
        y = top + (max_val - value) / span * chart_h
        circles.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" />')
    axis_y = top + chart_h
    axis = (
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{axis_y}" />'
    )
    return _svg(width, height, axis + "".join(circles), "scatter")


def _render_pie_svg(points: list[tuple[str, float]]) -> str:
    total = sum(abs(value) for _, value in points) or 1
    width = 720
    height = 300
    cx = 150
    cy = 145
    radius = 96
    start_angle = -90.0
    paths: list[str] = []
    legend: list[str] = []
    for idx, (label, value) in enumerate(points[:10]):
        fraction = abs(value) / total
        end_angle = start_angle + fraction * 360
        paths.append(_pie_slice(cx, cy, radius, start_angle, end_angle, idx))
        legend.append(
            '<div class="ob-legend__item">'
            f'<span style="--i:{idx}"></span><strong>{_escape(_short_label(label, 24))}</strong>'
            f'<em>{_escape(_format_value(value))}</em></div>'
        )
        start_angle = end_angle
    svg = _svg(width, height, "".join(paths), "pie")
    return f'<div class="ob-pie-layout">{svg}<div class="ob-legend">{"".join(legend)}</div></div>'


def _pie_slice(cx: int, cy: int, radius: int, start: float, end: float, idx: int) -> str:
    start_rad = math.radians(start)
    end_rad = math.radians(end)
    x1 = cx + radius * math.cos(start_rad)
    y1 = cy + radius * math.sin(start_rad)
    x2 = cx + radius * math.cos(end_rad)
    y2 = cy + radius * math.sin(end_rad)
    large_arc = 1 if end - start > 180 else 0
    return (
        f'<path class="slice slice-{idx % 10}" '
        f'd="M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large_arc} 1 '
        f'{x2:.2f} {y2:.2f} Z" />'
    )


def _svg(width: int, height: int, body: str, chart_class: str) -> str:
    return (
        f'<svg class="ob-chart ob-chart--{chart_class}" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Dashboard chart">'
        f"{body}</svg>"
    )


def _short_label(value: str, limit: int = 12) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[: max(0, limit - 1)]}..."


_DASHBOARD_CSS = """
:root {
  color-scheme: light;
  --ob-bg: #ffffff;
  --ob-text: #1a1a1a;
  --ob-text-secondary: rgba(26, 26, 26, 0.66);
  --ob-border: rgba(0, 0, 0, 0.08);
  --ob-panel: #ffffff;
  --ob-muted: rgba(0, 0, 0, 0.035);
  --ob-accent: #1f63c6;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--ob-bg);
  color: var(--ob-text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
.ob-dashboard {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0 32px;
}
.ob-dashboard__header {
  padding: 0 0 18px;
  border-bottom: 1px solid var(--ob-border);
}
.ob-dashboard__eyebrow {
  margin-bottom: 8px;
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0;
}
h1, h2, h3, p { margin: 0; }
h1 { font-size: 28px; line-height: 1.15; letter-spacing: 0; }
h2 { font-size: 18px; letter-spacing: 0; }
h3 { font-size: 14px; letter-spacing: 0; }
.ob-dashboard__description,
.ob-section__description,
.ob-panel__description,
.ob-kpi__note,
.ob-footer {
  color: var(--ob-text-secondary);
}
.ob-dashboard__description { max-width: 760px; margin-top: 8px; }
.ob-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  padding: 18px 0;
}
.ob-kpi {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--ob-border);
  border-radius: 8px;
  background: var(--ob-panel);
}
.ob-kpi__label {
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 600;
}
.ob-kpi__value {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 8px;
  font-size: 26px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
}
.ob-kpi__value span,
.ob-kpi__delta {
  color: var(--ob-text-secondary);
  font-size: 12px;
  font-weight: 500;
}
.ob-kpi__delta { display: inline-block; margin-top: 6px; }
.ob-kpi__note { margin-top: 6px; font-size: 12px; }
.ob-section {
  padding-top: 18px;
  border-top: 1px solid var(--ob-border);
}
.ob-section:first-of-type { border-top: 0; }
.ob-section__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.ob-panel-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 12px;
}
.ob-panel {
  grid-column: span 6;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--ob-border);
  border-radius: 8px;
  background: var(--ob-panel);
}
.ob-panel--table,
.ob-panel--text { grid-column: span 12; }
.ob-panel__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.ob-chart {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}
.ob-chart line {
  stroke: rgba(0, 0, 0, 0.18);
  stroke-width: 1;
}
.ob-chart text {
  fill: var(--ob-text-secondary);
  font-size: 11px;
}
.ob-chart--bar rect {
  fill: #1f63c6;
}
.ob-chart--line polyline {
  fill: none;
  stroke: #1f63c6;
  stroke-width: 2.5;
}
.ob-chart--line circle,
.ob-chart--scatter circle {
  fill: #ffffff;
  stroke: #1f63c6;
  stroke-width: 2;
}
.ob-chart--line .area {
  fill: rgba(31, 99, 198, 0.12);
  stroke: none;
}
.ob-chart--pie path { stroke: #ffffff; stroke-width: 2; }
.slice-0, .ob-legend span[style*="--i:0"] { fill: #1f63c6; background: #1f63c6; }
.slice-1, .ob-legend span[style*="--i:1"] { fill: #0f8268; background: #0f8268; }
.slice-2, .ob-legend span[style*="--i:2"] { fill: #9b6a00; background: #9b6a00; }
.slice-3, .ob-legend span[style*="--i:3"] { fill: #8d4bb3; background: #8d4bb3; }
.slice-4, .ob-legend span[style*="--i:4"] { fill: #b02020; background: #b02020; }
.slice-5, .ob-legend span[style*="--i:5"] { fill: #5f6f7d; background: #5f6f7d; }
.slice-6, .ob-legend span[style*="--i:6"] { fill: #2f6f8f; background: #2f6f8f; }
.slice-7, .ob-legend span[style*="--i:7"] { fill: #6b7f2a; background: #6b7f2a; }
.slice-8, .ob-legend span[style*="--i:8"] { fill: #7b5c43; background: #7b5c43; }
.slice-9, .ob-legend span[style*="--i:9"] { fill: #4f5aa8; background: #4f5aa8; }
.ob-pie-layout {
  display: grid;
  grid-template-columns: minmax(180px, 320px) minmax(160px, 1fr);
  gap: 12px;
  align-items: center;
}
.ob-legend { display: grid; gap: 7px; }
.ob-legend__item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) max-content;
  align-items: center;
  gap: 8px;
  color: var(--ob-text-secondary);
  font-size: 12px;
}
.ob-legend__item span {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.ob-legend__item strong {
  overflow: hidden;
  color: var(--ob-text);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ob-legend__item em {
  font-style: normal;
  font-variant-numeric: tabular-nums;
}
.ob-table-wrap {
  overflow: auto;
  border: 1px solid var(--ob-border);
  border-radius: 6px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th, td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--ob-border);
  text-align: left;
  white-space: nowrap;
}
th {
  background: var(--ob-muted);
  color: var(--ob-text-secondary);
  font-weight: 650;
}
tr:last-child td { border-bottom: 0; }
.ob-empty {
  display: flex;
  min-height: 220px;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--ob-border);
  border-radius: 6px;
  color: var(--ob-text-secondary);
}
.ob-footer {
  margin-top: 24px;
  padding-top: 12px;
  border-top: 1px solid var(--ob-border);
  font-size: 12px;
}
@media (max-width: 860px) {
  .ob-dashboard { width: min(100% - 24px, 1180px); padding-top: 18px; }
  h1 { font-size: 23px; }
  .ob-section__heading,
  .ob-panel__header { display: block; }
  .ob-panel { grid-column: span 12; }
  .ob-pie-layout { grid-template-columns: 1fr; }
}
"""
