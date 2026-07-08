"""Dashboard artifact generation from declarative OpenBench ViewModels."""

from __future__ import annotations

import json
import logging
import re
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
from openbench.output.generators.dashboard.normalizer import normalize_dashboard_view_model
from openbench.output.generators.dashboard.styles import _DASHBOARD_CSS

logger = logging.getLogger(__name__)


_TEMPLATE_CHART_SLOT_CLASSES = (
    "map",
    "bottom-chart",
    "donut",
    "big-chart",
    "large-area",
    "medium-area",
    "small-area",
    "chart-area",
    "graph-area",
    "plot-area",
    "visual-area",
    "viz-area",
    "canvas-area",
    "placeholder-gauge",
    "placeholder-line",
    "placeholder-bars",
    "chart-placeholder",
    "dashboard-placeholder",
    "chart-slot",
)

_TEMPLATE_PRIMARY_CHART_SLOT_CLASSES = ("map", "bottom-chart", "donut", "big-chart")

_TEMPLATE_KPI_SLOT_CLASSES = (
    "kpi",
    "kpi-card",
    "metric",
    "metric-card",
    "stat",
    "stat-card",
    "summary-metric",
    "summary-card",
)

_TEMPLATE_VISUAL_CLASS_KEYWORDS = (
    "area",
    "canvas",
    "chart",
    "donut",
    "graph",
    "map",
    "plot",
    "visual",
    "viz",
)

_TEMPLATE_VISUAL_CLASS_EXCLUSIONS = (
    "dashboard",
    "footer-card",
    "footer-grid",
    "grid",
    "kpi-card",
    "list",
    "main-grid",
    "panel",
    "right-item",
    "text-line",
    "top-grid",
)

_HYDRATED_TEMPLATE_CSS = """
.openbench-template-chart {
  display: flex;
  min-height: inherit;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  color: inherit;
}
.openbench-template-chart__title {
  width: 100%;
  color: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.25;
  opacity: 0.88;
}
.openbench-template-chart .ob-chart {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 140px;
  overflow: visible;
}
.openbench-template-chart .ob-chart line {
  stroke: rgba(185, 200, 223, 0.38);
  stroke-width: 1;
}
.openbench-template-chart .ob-chart text {
  fill: currentColor;
  font-size: 11px;
}
.openbench-template-chart .ob-chart--bar rect,
.openbench-template-chart .ob-chart--line circle,
.openbench-template-chart .ob-chart--scatter circle {
  fill: #4f8cff;
  stroke: #4f8cff;
}
.openbench-template-chart .ob-chart--line polyline {
  fill: none;
  stroke: #4f8cff;
  stroke-width: 2.5;
}
.openbench-template-chart .ob-chart--line .area {
  fill: rgba(79, 140, 255, 0.18);
  stroke: none;
}
.openbench-template-chart .ob-pie-layout {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(120px, 1fr) minmax(120px, 1fr);
  gap: 10px;
  align-items: center;
}
.openbench-template-chart .ob-legend {
  display: grid;
  gap: 6px;
}
.openbench-template-chart .ob-legend__item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) max-content;
  gap: 8px;
  align-items: center;
  font-size: 12px;
}
.openbench-template-chart .ob-legend__item span {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.openbench-template-chart .ob-legend__item strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.openbench-template-chart .ob-legend__item em {
  font-style: normal;
  opacity: 0.75;
}
.openbench-template-chart .slice-0,
.openbench-template-chart .ob-legend span[style*="--i:0"] { fill: #4f8cff; background: #4f8cff; }
.openbench-template-chart .slice-1,
.openbench-template-chart .ob-legend span[style*="--i:1"] { fill: #49d17f; background: #49d17f; }
.openbench-template-chart .slice-2,
.openbench-template-chart .ob-legend span[style*="--i:2"] { fill: #ffb54a; background: #ffb54a; }
.openbench-template-chart .slice-3,
.openbench-template-chart .ob-legend span[style*="--i:3"] { fill: #c084fc; background: #c084fc; }
.openbench-template-chart .slice-4,
.openbench-template-chart .ob-legend span[style*="--i:4"] { fill: #fb7185; background: #fb7185; }
.openbench-template-text,
.openbench-template-right-title,
.openbench-template-footer-title {
  color: inherit;
  font-weight: 600;
}
.openbench-template-text {
  opacity: 0.92;
}
.openbench-template-right-sub,
.openbench-template-footer-desc {
  color: inherit;
  font-size: 12px;
  line-height: 1.35;
  opacity: 0.68;
}
.openbench-template-thumb {
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
  font-size: 22px;
  font-weight: 700;
}
.openbench-template-footer-value {
  margin-top: 12px;
  color: inherit;
  font-size: 24px;
  font-weight: 700;
}
"""


_HtmlBlock = dict[str, Any]


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
        template_source = self._resolve_template_source(options)
        template_source_kind = "user" if template_source else "default"
        template_source_format = (
            str(template_source["metadata"].get("format") or "unknown")
            if template_source
            else "default"
        )
        template_source_name = (
            str(template_source["metadata"].get("source") or "inline-template")
            if template_source
            else str(template or self.template)
        )
        logger.info(
            "[dashboard] template_source=%s template_format=%s template_name=%s title=%s",
            template_source_kind,
            template_source_format,
            template_source_name,
            view_model.get("title"),
        )
        html_text = self._render_html(
            view_model,
            template or self.template,
            template_source=template_source,
        )
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
                "custom_template": template_source["metadata"] if template_source else None,
                "template_source": template_source_kind,
                "template_format": template_source_format,
                "template_name": template_source_name,
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
        return normalize_dashboard_view_model(content, title=title)

    def _render_html(
        self,
        view_model: dict[str, Any],
        template: str,
        *,
        template_source: dict[str, Any] | None = None,
    ) -> str:
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
        body_html = "".join(body_parts)
        if template_source:
            return self._render_custom_template(
                template_source=template_source,
                view_model=view_model,
                title=title,
                description=description,
                body_html=body_html,
                data_json=data_json,
                generated_at=generated_at,
                template=template,
            )
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
    {body_html}
    <footer class="ob-footer">Generated by OpenBench on {generated_at}</footer>
  </main>
  <script type="application/json" id="openbench-dashboard-view-model">{data_json}</script>
</body>
</html>
"""

    def _resolve_template_source(self, options: dict[str, Any]) -> dict[str, Any] | None:
        template_text = options.get("template_text")
        template_path = options.get("template_path")
        template_format = str(options.get("template_format") or "").strip().lower()
        source_name = ""

        if template_path:
            path = Path(str(template_path)).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"Dashboard template file not found: {template_path}")
            template_text = path.read_text(encoding="utf-8")
            source_name = path.name
            if not template_format:
                template_format = "html" if path.suffix.lower() in {".html", ".htm"} else "markdown"
        elif template_text:
            source_name = "inline-template"
            if not template_format:
                text = str(template_text).lstrip()
                template_format = "html" if text.lower().startswith(("<!doctype", "<html")) else "markdown"

        if not template_text:
            return None

        normalized_format = "html" if template_format in {"html", "htm"} else "markdown"
        text_value = str(template_text)
        return {
            "text": text_value,
            "format": normalized_format,
            "metadata": {
                "source": source_name,
                "format": normalized_format,
                "chars": len(text_value),
            },
        }

    def _render_custom_template(
        self,
        *,
        template_source: dict[str, Any],
        view_model: dict[str, Any],
        title: str,
        description: str,
        body_html: str,
        data_json: str,
        generated_at: str,
        template: str,
    ) -> str:
        text = str(template_source["text"])
        fmt = str(template_source["format"])
        if fmt == "html":
            return self._render_html_template(
                template_text=text,
                view_model=view_model,
                title=title,
                description=description,
                body_html=body_html,
                data_json=data_json,
                generated_at=generated_at,
                template=template,
            )
        return self._render_markdown_design_template(
            design_text=text,
            title=title,
            description=description,
            body_html=body_html,
            data_json=data_json,
            generated_at=generated_at,
            template=template,
        )

    def _render_html_template(
        self,
        *,
        template_text: str,
        view_model: dict[str, Any],
        title: str,
        description: str,
        body_html: str,
        data_json: str,
        generated_at: str,
        template: str,
    ) -> str:
        safe_template = self._strip_unsafe_html(template_text)
        main_html = (
            f'<main class="ob-dashboard" data-template="{_escape(template)}">'
            f"{body_html}"
            f'<footer class="ob-footer">Generated by OpenBench on {generated_at}</footer>'
            "</main>"
        )
        replacements = {
            "title": title,
            "description": description,
            "body": main_html,
            "dashboard_body": main_html,
            "kpis": "",
            "sections": "",
            "generated_at": _escape(generated_at),
            "openbench_css": _DASHBOARD_CSS,
            "dashboard_json": data_json,
        }
        rendered = safe_template
        matched_placeholder = False
        for key, value in replacements.items():
            token = "{{" + key + "}}"
            if token in rendered:
                matched_placeholder = True
                rendered = rendered.replace(token, value)
        if not matched_placeholder:
            rendered, hydrated = self._hydrate_html_template(
                rendered,
                view_model=view_model,
                title=title,
                generated_at=generated_at,
            )
            if not hydrated:
                rendered = self._inject_before_body_end(rendered, main_html)
        rendered = self._ensure_head_assets(rendered, title=title)
        return self._ensure_view_model_script(rendered, data_json)

    def _hydrate_html_template(
        self,
        html_text: str,
        *,
        view_model: dict[str, Any],
        title: str,
        generated_at: str,
    ) -> tuple[str, bool]:
        rendered = self._replace_title_tag(html_text, title)
        rendered = self._hydrate_template_kpis(rendered, view_model)
        rendered, chart_count = self._hydrate_template_chart_slots(rendered, view_model)
        rendered = self._hydrate_template_text(rendered, view_model, generated_at=generated_at)
        hydrated = chart_count > 0 or 'data-openbench-filled="kpi"' in rendered
        if hydrated:
            rendered = self._ensure_hydrated_template_assets(rendered)
        return rendered, hydrated

    def _hydrate_template_kpis(self, html_text: str, view_model: dict[str, Any]) -> str:
        kpis = [item for item in view_model.get("kpis") or [] if isinstance(item, dict)]
        if not kpis:
            return html_text
        datasets = _normalize_datasets(view_model.get("datasets"))
        blocks = self._find_html_blocks_by_class(html_text, "div", _TEMPLATE_KPI_SLOT_CLASSES)
        if not blocks:
            return html_text
        rendered = html_text
        for idx, block in reversed(list(enumerate(blocks[: len(kpis)]))):
            item = kpis[idx]
            open_tag = self._add_attribute_to_tag(
                self._add_class_to_tag(block["open_tag"], "openbench-template-kpi"),
                "data-openbench-filled",
                "kpi",
            )
            content = self._render_template_kpi_content(
                item,
                datasets,
                block.get("classes", ()),
            )
            rendered = (
                rendered[: block["start"]]
                + open_tag
                + content
                + rendered[block["close_start"] : block["end"]]
                + rendered[block["end"] :]
            )
        return rendered

    def _hydrate_template_chart_slots(
        self, html_text: str, view_model: dict[str, Any]
    ) -> tuple[str, int]:
        chart_items = self._template_chart_items(view_model)
        if not chart_items:
            return html_text, 0

        rendered = html_text
        chart_titles: list[str] = []
        used: set[int] = set()
        replacements: list[tuple[_HtmlBlock, int]] = []

        for block in self._find_template_chart_blocks(rendered):
            if any(existing["start"] == block["start"] for existing, _ in replacements):
                continue
            chart_idx = self._select_chart_for_slot(
                chart_items,
                used,
                block.get("classes", ()),
                fallback_index=len(replacements),
            )
            if chart_idx is None:
                continue
            used.add(chart_idx)
            replacements.append((block, chart_idx))

        if not replacements:
            return html_text, 0

        chart_titles = [
            str(chart_items[chart_idx].get("title") or "Chart")
            for _, chart_idx in sorted(replacements, key=lambda item: int(item[0]["start"]))
        ]

        # Apply replacements from bottom to top so offsets stay valid.
        replacements.sort(key=lambda item: int(item[0]["start"]), reverse=True)
        for block, chart_idx in replacements:
            item = chart_items[chart_idx]
            open_tag = self._add_attribute_to_tag(
                self._add_class_to_tag(block["open_tag"], "openbench-template-chart"),
                "data-openbench-filled",
                "chart",
            )
            chart_html = self._render_template_chart_content(item, view_model)
            rendered = (
                rendered[: block["start"]]
                + open_tag
                + chart_html
                + rendered[block["close_start"] : block["end"]]
                + rendered[block["end"] :]
            )

        rendered = self._hydrate_template_panel_titles(rendered, chart_titles)
        return rendered, len(replacements)

    def _hydrate_template_panel_titles(self, html_text: str, chart_titles: list[str]) -> str:
        if not chart_titles:
            return html_text
        blocks = self._find_html_blocks_by_class(html_text, "div", ("panel-title",))
        if not blocks:
            return html_text
        rendered = html_text
        for idx, block in reversed(list(enumerate(blocks[: len(chart_titles)]))):
            rendered = (
                rendered[: block["open_end"]]
                + _escape(chart_titles[idx])
                + rendered[block["close_start"] :]
            )
        return rendered

    def _hydrate_template_text(
        self, html_text: str, view_model: dict[str, Any], *, generated_at: str
    ) -> str:
        rendered = html_text
        description = str(view_model.get("description") or "").strip()
        if description:
            for block in reversed(self._find_html_blocks_by_class(rendered, "div", ("bubble",))[:1]):
                rendered = (
                    rendered[: block["open_end"]]
                    + _escape(description)
                    + rendered[block["close_start"] :]
                )
        replacements = {
            "Dashboard response placeholder...": description
            or f"Generated by OpenBench on {generated_at}",
            "Issue Placeholder": "",
        }
        for old, new in replacements.items():
            rendered = rendered.replace(old, _escape(new))
        summaries = self._template_summary_items(view_model, generated_at=generated_at)
        rendered = self._hydrate_template_list_items(rendered, summaries)
        rendered = self._hydrate_template_right_items(rendered, summaries)
        rendered = self._hydrate_template_footer_cards(rendered, summaries)
        return rendered

    def _render_template_kpi_content(
        self,
        item: dict[str, Any],
        datasets: dict[str, list[dict[str, Any]]],
        classes: tuple[str, ...] = (),
    ) -> str:
        label = _escape(str(item.get("label") or item.get("title") or "KPI"))
        value = _escape(_format_kpi_value(item, datasets))
        note = _escape(
            str(
                item.get("delta")
                or item.get("change")
                or item.get("note")
                or item.get("description")
                or ""
            )
        )
        class_set = set(classes)
        if "kpi-card" in class_set:
            title_class, value_class, note_class = "kpi-title", "kpi-value", "kpi-desc"
        elif "metric-card" in class_set or "metric" in class_set:
            title_class, value_class, note_class = "metric-title", "metric-value", "metric-desc"
        elif "stat-card" in class_set or "stat" in class_set:
            title_class, value_class, note_class = "stat-title", "stat-value", "stat-desc"
        else:
            title_class, value_class, note_class = "title", "value", "sub"
        note_html = (
            f'<div class="{note_class}">{note}</div>'
            if note
            else f'<div class="{note_class}">OpenBench metric</div>'
        )
        return (
            f'<div class="{title_class}">{label}</div>'
            f'<div class="{value_class}">{value}</div>'
            f"{note_html}"
        )

    def _template_chart_items(self, view_model: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for section in view_model.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_items = (
                section.get("items")
                or section.get("components")
                or section.get("widgets")
                or section.get("panels")
                or section.get("charts")
                or []
            )
            for item in section_items:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or item.get("kind") or "chart").lower()
                if item_type in {"chart", "bar", "line", "area", "pie", "scatter"}:
                    items.append(item)
        return items

    def _select_chart_for_slot(
        self,
        chart_items: list[dict[str, Any]],
        used: set[int],
        classes: tuple[str, ...],
        *,
        fallback_index: int = 0,
    ) -> int | None:
        preferred: tuple[str, ...] = ()
        if "donut" in classes or "pie" in classes:
            preferred = ("pie", "donut")
        elif "placeholder-line" in classes or "line-area" in classes or "trend-area" in classes:
            preferred = ("line", "area")
        elif "placeholder-bars" in classes or "bar-area" in classes:
            preferred = ("bar", "column")

        for idx, item in enumerate(chart_items):
            if idx in used:
                continue
            chart_type = str(
                item.get("chart_type")
                or item.get("chartType")
                or item.get("visualization")
                or item.get("type")
                or "bar"
            ).lower()
            if preferred and chart_type in preferred:
                return idx
        for idx in range(len(chart_items)):
            if idx not in used:
                return idx
        if preferred:
            for idx, item in enumerate(chart_items):
                chart_type = str(
                    item.get("chart_type")
                    or item.get("chartType")
                    or item.get("visualization")
                    or item.get("type")
                    or "bar"
                ).lower()
                if chart_type in preferred:
                    return idx
        if chart_items:
            return fallback_index % len(chart_items)
        return None

    def _render_template_chart_content(
        self, item: dict[str, Any], view_model: dict[str, Any]
    ) -> str:
        datasets = view_model.get("datasets") or {}
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
            or item.get("x_field")
            or item.get("xField")
            or _first_category_key(records)
        )
        y_key = str(
            item.get("y")
            or item.get("y_key")
            or item.get("yKey")
            or item.get("y_axis")
            or item.get("yAxis")
            or item.get("y_field")
            or item.get("yField")
            or _first_numeric_key(records, fallback=x_key)
        )
        title = _escape(str(item.get("title") or "Chart"))
        chart_svg = _render_chart_svg(chart_type, records, x_key=x_key, y_key=y_key)
        return f'<div class="openbench-template-chart__title">{title}</div>{chart_svg}'

    def _template_summary_items(
        self, view_model: dict[str, Any], *, generated_at: str
    ) -> list[dict[str, str]]:
        datasets = _normalize_datasets(view_model.get("datasets"))
        summaries: list[dict[str, str]] = []
        for item in view_model.get("kpis") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("label") or item.get("title") or "Metric").strip()
            value = _format_kpi_value(item, datasets)
            description = str(
                item.get("description")
                or item.get("note")
                or item.get("delta")
                or item.get("change")
                or ""
            ).strip()
            summaries.append(
                {
                    "title": title or "Metric",
                    "value": value,
                    "description": description or "Dashboard metric",
                }
            )
        for chart in self._template_chart_items(view_model):
            title = str(chart.get("title") or "Chart").strip()
            records = self._resolve_item_data(chart, view_model.get("datasets") or {})
            summaries.append(
                {
                    "title": title or "Chart",
                    "value": f"{len(records):,} points",
                    "description": "Visual analysis panel",
                }
            )
        if not summaries:
            summaries.append(
                {
                    "title": str(view_model.get("title") or "Dashboard"),
                    "value": "OpenBench",
                    "description": f"Generated on {generated_at}",
                }
            )
        return summaries

    def _hydrate_template_list_items(
        self, html_text: str, summaries: list[dict[str, str]]
    ) -> str:
        blocks = self._find_html_blocks_by_class(html_text, "div", ("list-item",))
        if not blocks or not summaries:
            return html_text
        rendered = html_text
        for idx, block in reversed(list(enumerate(blocks))):
            item = summaries[idx % len(summaries)]
            open_tag = self._add_attribute_to_tag(
                self._add_class_to_tag(block["open_tag"], "openbench-template-text"),
                "data-openbench-filled",
                "text",
            )
            content = (
                f'<strong>{_escape(item["title"])}</strong>: '
                f'{_escape(item["description"] or item["value"])}'
            )
            rendered = (
                rendered[: block["start"]]
                + open_tag
                + content
                + rendered[block["close_start"] : block["end"]]
                + rendered[block["end"] :]
            )
        return rendered

    def _hydrate_template_right_items(
        self, html_text: str, summaries: list[dict[str, str]]
    ) -> str:
        blocks = self._find_html_blocks_by_class(html_text, "div", ("right-item",))
        if not blocks or not summaries:
            return html_text
        rendered = html_text
        for idx, block in reversed(list(enumerate(blocks))):
            item = summaries[idx % len(summaries)]
            open_tag = self._add_attribute_to_tag(
                self._add_class_to_tag(block["open_tag"], "openbench-template-summary"),
                "data-openbench-filled",
                "summary",
            )
            content = (
                f'<div class="thumb openbench-template-thumb">{idx + 1}</div>'
                "<div>"
                f'<div class="openbench-template-right-title">{_escape(item["title"])}</div>'
                f'<div class="openbench-template-right-sub">{_escape(item["value"])}</div>'
                "</div>"
            )
            rendered = (
                rendered[: block["start"]]
                + open_tag
                + content
                + rendered[block["close_start"] : block["end"]]
                + rendered[block["end"] :]
            )
        return rendered

    def _hydrate_template_footer_cards(
        self, html_text: str, summaries: list[dict[str, str]]
    ) -> str:
        blocks = self._find_html_blocks_by_class(html_text, "div", ("footer-card",))
        if not blocks or not summaries:
            return html_text
        rendered = html_text
        for idx, block in reversed(list(enumerate(blocks))):
            item = summaries[idx % len(summaries)]
            open_tag = self._add_attribute_to_tag(
                self._add_class_to_tag(block["open_tag"], "openbench-template-footer"),
                "data-openbench-filled",
                "summary",
            )
            content = (
                f'<div class="panel-title openbench-template-footer-title">{_escape(item["title"])}</div>'
                f'<div class="openbench-template-footer-value">{_escape(item["value"])}</div>'
                f'<div class="openbench-template-footer-desc">{_escape(item["description"])}</div>'
            )
            rendered = (
                rendered[: block["start"]]
                + open_tag
                + content
                + rendered[block["close_start"] : block["end"]]
                + rendered[block["end"] :]
            )
        return rendered

    @staticmethod
    def _replace_title_tag(html_text: str, title: str) -> str:
        if re.search(r"<title\b", html_text, flags=re.IGNORECASE):
            return re.sub(
                r"<title\b[^>]*>.*?</title\s*>",
                f"<title>{title}</title>",
                html_text,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
        return html_text

    def _find_template_chart_blocks(self, html_text: str) -> list[_HtmlBlock]:
        blocks: list[_HtmlBlock] = []
        seen: set[int] = set()
        for class_group in (_TEMPLATE_PRIMARY_CHART_SLOT_CLASSES, _TEMPLATE_CHART_SLOT_CLASSES):
            for block in self._find_html_blocks_by_class(html_text, "div", class_group):
                start = int(block["start"])
                if start in seen:
                    continue
                seen.add(start)
                blocks.append(block)

        for block in self._find_html_blocks(html_text, "div"):
            start = int(block["start"])
            if start in seen or not self._is_template_visual_slot(html_text, block):
                continue
            seen.add(start)
            blocks.append(block)

        return sorted(blocks, key=lambda block: int(block["start"]))

    @staticmethod
    def _is_template_visual_slot(html_text: str, block: _HtmlBlock) -> bool:
        classes = tuple(str(part).lower() for part in block.get("classes", ()))
        if not classes:
            return False
        if any(name in classes for name in _TEMPLATE_VISUAL_CLASS_EXCLUSIONS):
            return False
        inner = html_text[int(block["open_end"]) : int(block["close_start"])].strip()
        if inner and not DashboardGenerator._is_placeholder_inner_html(inner):
            return False
        return any(
            keyword in class_name
            for class_name in classes
            for keyword in _TEMPLATE_VISUAL_CLASS_KEYWORDS
        )

    @staticmethod
    def _is_placeholder_inner_html(inner_html: str) -> bool:
        text = re.sub(r"<[^>]+>", " ", inner_html)
        text = re.sub(r"\s+", " ", text).strip().lower()
        if not text:
            return True
        placeholder_terms = (
            "--",
            "chart",
            "empty",
            "graph",
            "placeholder",
            "visualization",
        )
        return any(term in text for term in placeholder_terms)

    @staticmethod
    def _find_html_blocks_by_class(
        html_text: str, tag: str, class_names: tuple[str, ...]
    ) -> list[_HtmlBlock]:
        return [
            block
            for block in DashboardGenerator._find_html_blocks(html_text, tag)
            if any(name in block.get("classes", ()) for name in class_names)
        ]

    @staticmethod
    def _find_html_blocks(html_text: str, tag: str) -> list[_HtmlBlock]:
        blocks: list[_HtmlBlock] = []
        open_tag_re = re.compile(rf"<{re.escape(tag)}\b[^>]*>", flags=re.IGNORECASE)
        for match in open_tag_re.finditer(html_text):
            open_tag = match.group(0)
            classes = DashboardGenerator._classes_from_tag(open_tag)
            close_start, end = DashboardGenerator._matching_tag_bounds(
                html_text, tag, match.start()
            )
            if close_start is None or end is None:
                continue
            blocks.append(
                {
                    "start": match.start(),
                    "open_end": match.end(),
                    "close_start": close_start,
                    "end": end,
                    "open_tag": open_tag,
                    "classes": classes,
                }
            )
        return blocks

    @staticmethod
    def _matching_tag_bounds(
        html_text: str, tag: str, start: int
    ) -> tuple[int | None, int | None]:
        tag_re = re.compile(rf"<(/?){re.escape(tag)}\b[^>]*>", flags=re.IGNORECASE)
        depth = 0
        for match in tag_re.finditer(html_text, start):
            is_close = bool(match.group(1))
            if is_close:
                depth -= 1
                if depth == 0:
                    return match.start(), match.end()
            elif not match.group(0).rstrip().endswith("/>"):
                depth += 1
        return None, None

    @staticmethod
    def _classes_from_tag(open_tag: str) -> tuple[str, ...]:
        match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", open_tag, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ()
        return tuple(part for part in re.split(r"\s+", match.group(2).strip()) if part)

    @staticmethod
    def _add_class_to_tag(open_tag: str, class_name: str) -> str:
        match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", open_tag, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return open_tag[:-1] + f' class="{class_name}">'
        classes = match.group(2).split()
        if class_name in classes:
            return open_tag
        value = " ".join([*classes, class_name])
        return open_tag[: match.start(2)] + value + open_tag[match.end(2) :]

    @staticmethod
    def _add_attribute_to_tag(open_tag: str, name: str, value: str) -> str:
        if re.search(rf"\b{re.escape(name)}\s*=", open_tag, flags=re.IGNORECASE):
            return open_tag
        return open_tag[:-1] + f' {name}="{_escape(value)}">'

    @staticmethod
    def _ensure_hydrated_template_assets(html_text: str) -> str:
        if "data-openbench-template-hydration" in html_text:
            return html_text
        style = f'<style data-openbench-template-hydration="true">\n{_HYDRATED_TEMPLATE_CSS}\n</style>'
        if re.search(r"</head\s*>", html_text, flags=re.IGNORECASE):
            return re.sub(
                r"</head\s*>",
                style + "\n</head>",
                html_text,
                count=1,
                flags=re.IGNORECASE,
            )
        return style + "\n" + html_text

    def _render_markdown_design_template(
        self,
        *,
        design_text: str,
        title: str,
        description: str,
        body_html: str,
        data_json: str,
        generated_at: str,
        template: str,
    ) -> str:
        css = "\n".join(_extract_fenced_blocks(design_text, "css"))
        design_summary = _escape(_first_markdown_heading(design_text) or "Uploaded dashboard design")
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
{_DASHBOARD_CSS}
{css}
  </style>
</head>
<body data-template="{_escape(template)}" data-custom-template="markdown-design">
  <main class="ob-dashboard">
    <div class="ob-dashboard__eyebrow">{design_summary}</div>
    {body_html}
    <footer class="ob-footer">Generated by OpenBench on {generated_at}</footer>
  </main>
  <script type="application/json" id="openbench-dashboard-view-model">{data_json}</script>
</body>
</html>
"""

    @staticmethod
    def _strip_unsafe_html(template_text: str) -> str:
        without_scripts = re.sub(
            r"<script\b[^>]*>.*?</script\s*>",
            "",
            template_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\son[a-z]+\s*=\s*(['\"]).*?\1", "", without_scripts, flags=re.IGNORECASE)

    @staticmethod
    def _inject_before_body_end(html_text: str, body_html: str) -> str:
        if re.search(r"</body\s*>", html_text, flags=re.IGNORECASE):
            return re.sub(
                r"</body\s*>",
                body_html + "\n</body>",
                html_text,
                count=1,
                flags=re.IGNORECASE,
            )
        return html_text + "\n" + body_html

    @staticmethod
    def _ensure_head_assets(html_text: str, *, title: str) -> str:
        style = f"<style>\n{_DASHBOARD_CSS}\n</style>"
        if "{{openbench_css}}" not in html_text and "<style" not in html_text.lower():
            if re.search(r"</head\s*>", html_text, flags=re.IGNORECASE):
                html_text = re.sub(
                    r"</head\s*>",
                    style + "\n</head>",
                    html_text,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                html_text = f"<!doctype html><html><head><title>{title}</title>{style}</head><body>{html_text}</body></html>"
        return html_text

    @staticmethod
    def _ensure_view_model_script(html_text: str, data_json: str) -> str:
        if "openbench-dashboard-view-model" in html_text:
            return html_text
        script = (
            '<script type="application/json" id="openbench-dashboard-view-model">'
            f"{data_json}</script>"
        )
        return DashboardGenerator._inject_before_body_end(html_text, script)

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
        if isinstance(data, dict):
            values = data.get("values") or data.get("records") or data.get("rows")
            if isinstance(values, list):
                return [row for row in values if isinstance(row, dict)]
        if isinstance(data, str) and data in datasets:
            return datasets[data]
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
            or item.get("x_field")
            or item.get("xField")
            or _first_category_key(records)
        )
        y_key = str(
            item.get("y")
            or item.get("y_key")
            or item.get("yKey")
            or item.get("y_axis")
            or item.get("yAxis")
            or item.get("y_field")
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
        raw_content = item.get("content") or item.get("text") or item.get("value") or ""
        content = _escape(str(raw_content)) if isinstance(raw_content, (str, int, float, bool)) else ""
        return (
            f'<article class="ob-panel ob-panel--text"><h3>{title}</h3><p>{content}</p></article>'
        )


def _extract_fenced_blocks(text: str, language: str) -> list[str]:
    pattern = rf"```{re.escape(language)}\s*(.*?)```"
    return [match.strip() for match in re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL)]


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return None
