"""
Chart content renderer.

Converts chart data dicts to A2UI ObChart components.
Supports: bar, line, pie, scatter, area chart types.
"""

import uuid
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry

VALID_CHART_TYPES = ("bar", "line", "pie", "scatter", "area")


@ContentRendererRegistry.register("chart", "default", description="Chart data renderer")
class ChartRenderer(ContentRenderer):
    """Renders chart data to ObChart A2UI components.

    Expected input format:
        {"type": "bar", "data": [...], "options": {...}}

    - type: One of bar, line, pie, scatter, area
    - data: Recharts-compatible data array
    - options: Optional chart configuration
    - title: Optional chart title
    - width: Optional width (default "100%")
    - height: Optional height (default "300px")
    """

    @property
    def content_type(self) -> str:
        return "chart"

    def detect(self, content: Any) -> bool:
        """Detect if content is chart data.

        Matches dicts with "type" key whose value is a valid chart type,
        and a "data" key.
        """
        if not isinstance(content, dict):
            return False
        chart_type = content.get("type")
        return chart_type in VALID_CHART_TYPES and "data" in content

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert chart data to ObChart component."""
        chart_type = content["type"]
        data = content["data"]
        options = content.get("options", {})
        title = content.get("title")
        width = content.get("width", "100%")
        height = content.get("height", "300px")

        components: list[A2UIComponent] = []

        # Optional title as Text component
        if title:
            components.append(A2UIComponent(
                id=_gen_id("chart-title"),
                component="Text",
                properties={"text": title, "variant": "h4"},
            ))

        # ObChart component
        chart_props: dict[str, Any] = {
            "chartType": chart_type,
            "data": data,
            "width": width,
            "height": height,
        }
        if options:
            chart_props["options"] = options

        components.append(A2UIComponent(
            id=_gen_id("chart"),
            component="ObChart",
            properties=chart_props,
        ))

        return components


def _gen_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
