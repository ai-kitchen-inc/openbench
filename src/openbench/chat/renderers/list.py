"""
List content renderer.

Converts list data dicts to A2UI List components with Text children.
Supports ordered and unordered lists with optional subtitles.
"""

from __future__ import annotations

import uuid
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry


@ContentRendererRegistry.register("list", "default", description="Structured list renderer")
class ListRenderer(ContentRenderer):
    """Renders list data to A2UI List components.

    Expected input format:
        {
            "listType": "ordered" | "unordered",
            "title": "My List",
            "items": ["Item 1", "Item 2"]
        }

    Items can be:
    - Strings: rendered as Text(variant="body")
    - Dicts with "text" key: rendered as Text(variant="body")
      - Optional "subtitle" key: additional Text(variant="caption") below

    - listType: "ordered" or "unordered" (required)
    - items: Non-empty list of items (required)
    - title: Optional title displayed above the list
    - maxHeight: Optional max height for scrollable list
    """

    @property
    def content_type(self) -> str:
        return "list"

    def detect(self, content: Any) -> bool:
        """Detect if content is list data.

        Matches dicts with "items" key (non-empty list) and "listType" key.
        """
        if not isinstance(content, dict):
            return False
        items = content.get("items")
        return "listType" in content and isinstance(items, list) and len(items) > 0

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert list data to A2UI List component with Text children."""
        items = content["items"]
        list_type = content["listType"]
        title = content.get("title")
        max_height = content.get("maxHeight")
        ordered = list_type == "ordered"

        components: list[A2UIComponent] = []

        # Optional title as Text component
        if title:
            components.append(
                A2UIComponent(
                    id=_gen_id("list-title"),
                    component="Text",
                    properties={"text": title, "variant": "h4"},
                )
            )

        # Build child components for each item
        child_ids: list[str] = []
        child_components: list[A2UIComponent] = []

        for item in items:
            if isinstance(item, str):
                item_id = _gen_id("list-item")
                child_ids.append(item_id)
                child_components.append(
                    A2UIComponent(
                        id=item_id,
                        component="Text",
                        properties={"text": item, "variant": "body"},
                    )
                )
            elif isinstance(item, dict) and "text" in item:
                subtitle = item.get("subtitle")
                if subtitle:
                    # Wrap in Column for text + subtitle
                    col_id = _gen_id("list-item-col")
                    text_id = _gen_id("list-item-text")
                    sub_id = _gen_id("list-item-sub")
                    child_ids.append(col_id)
                    child_components.append(
                        A2UIComponent(
                            id=col_id,
                            component="Column",
                            properties={
                                "children": [text_id, sub_id],
                                "gap": "2px",
                            },
                        )
                    )
                    child_components.append(
                        A2UIComponent(
                            id=text_id,
                            component="Text",
                            properties={"text": item["text"], "variant": "body"},
                        )
                    )
                    child_components.append(
                        A2UIComponent(
                            id=sub_id,
                            component="Text",
                            properties={"text": subtitle, "variant": "caption"},
                        )
                    )
                else:
                    item_id = _gen_id("list-item")
                    child_ids.append(item_id)
                    child_components.append(
                        A2UIComponent(
                            id=item_id,
                            component="Text",
                            properties={"text": item["text"], "variant": "body"},
                        )
                    )

        # Card wrapper
        card_id = _gen_id("list-card")
        list_id = _gen_id("list")

        list_props: dict[str, Any] = {
            "children": child_ids,
            "ordered": ordered,
        }
        if max_height:
            list_props["maxHeight"] = max_height

        card_props: dict[str, Any] = {
            "children": [list_id],
            "elevation": 0,
            "padding": "24px",
        }

        components.append(A2UIComponent(id=card_id, component="Card", properties=card_props))
        components.append(A2UIComponent(id=list_id, component="List", properties=list_props))
        components.extend(child_components)

        return components


def _gen_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
