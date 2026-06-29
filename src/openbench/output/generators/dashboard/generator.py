"""Dashboard artifact generation from declarative OpenBench ViewModels."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from openbench.core.abstractions import GeneratedOutput, OutputGenerator
from openbench.output.generators.dashboard.charts import _render_chart_svg
from openbench.output.generators.dashboard.datasets import (
    _first_category_key,
    _first_numeric_key,
    _format_kpi_value,
    _normalize_datasets,
    _normalize_table_columns,
    _table_cell_value,
)
from openbench.output.generators.dashboard.formatting import _escape, _format_value, _slugify
from openbench.output.generators.dashboard.styles import _DASHBOARD_CSS

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
            self._render_kpis(
                view_model.get("kpis") or [], _normalize_datasets(view_model.get("datasets"))
            ),
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

    def _render_kpis(
        self, kpis: list[Any], datasets: dict[str, list[dict[str, Any]]] | None = None
    ) -> str:
        datasets = datasets or {}
        cards: list[str] = []
        for item in kpis:
            if not isinstance(item, dict):
                continue
            label = _escape(str(item.get("label") or item.get("title") or "KPI"))
            value = _escape(_format_kpi_value(item, datasets))
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
            items = (
                section.get("items")
                or section.get("components")
                or section.get("widgets")
                or section.get("panels")
                or section.get("charts")
                or section.get("cards")
                or []
            )
            desc_html = (
                f'<p class="ob-section__description">{description}</p>' if description else ""
            )
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
            return self._render_kpis([item], datasets)
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
        chart_type = str(
            item.get("chart_type")
            or item.get("chartType")
            or item.get("visualization")
            or item.get("type")
            or "bar"
        )
        records = self._resolve_item_data(item, datasets)
        x_key = str(
            item.get("x")
            or item.get("x_key")
            or item.get("xKey")
            or item.get("x_axis")
            or item.get("xAxis")
            or item.get("xField")
            or _first_category_key(records)
        )
        y_key = str(
            item.get("y")
            or item.get("y_key")
            or item.get("yKey")
            or item.get("y_axis")
            or item.get("yAxis")
            or item.get("yField")
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
            f'<article class="ob-panel ob-panel--text"><h3>{title}</h3><p>{content}</p></article>'
        )
