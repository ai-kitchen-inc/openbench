"""
Table content renderer.

Converts table data dicts to A2UI ObTable components.
Supports striped rows and compact mode.
"""

from __future__ import annotations

from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id


@ContentRendererRegistry.register("table", "default", description="Structured table renderer")
class TableRenderer(ContentRenderer):
    """Renders table data to ObTable A2UI components.

    Expected input format:
        {
            "headers": ["Col A", "Col B"],
            "rows": [["val1", "val2"], ["val3", "val4"]],
            "title": "Optional title",
            "caption": "Optional caption",
            "striped": True,
            "compact": False,
        }

    - headers: Non-empty list of column header strings (required)
    - rows: List of row arrays (required)
    - title: Optional title displayed above the table
    - caption: Optional caption below the title
    - striped: Alternate row shading (default True)
    - compact: Reduced padding (default False)
    """

    @property
    def content_type(self) -> str:
        return "table"

    def detect(self, content: Any) -> bool:
        """Detect if content is table data.

        Matches dicts with "headers" key (non-empty list) and "rows" key (list).
        """
        if not isinstance(content, dict):
            return False
        headers = content.get("headers")
        rows = content.get("rows")
        return isinstance(headers, list) and len(headers) > 0 and isinstance(rows, list)

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert table data to ObTable component."""
        headers = content["headers"]
        rows = content["rows"]
        title = content.get("title")
        caption = content.get("caption")
        striped = content.get("striped", True)
        compact = content.get("compact", False)

        components: list[A2UIComponent] = []

        # Optional title as Text component
        if title:
            components.append(
                A2UIComponent(
                    id=gen_id("table-title"),
                    component="Text",
                    properties={"text": title, "variant": "h4"},
                )
            )

        # Optional caption as Text component
        if caption:
            components.append(
                A2UIComponent(
                    id=gen_id("table-caption"),
                    component="Text",
                    properties={"text": caption, "variant": "caption"},
                )
            )

        # ObTable component
        table_props: dict[str, Any] = {
            "headers": headers,
            "rows": rows,
            "striped": striped,
            "compact": compact,
        }

        components.append(
            A2UIComponent(
                id=gen_id("table"),
                component="ObTable",
                properties=table_props,
            )
        )

        return components
