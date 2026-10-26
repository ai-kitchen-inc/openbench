"""
Tabs content renderer.

Converts tabbed content dicts to A2UI Tabs components with ObMarkdown children.
Each tab has a label and markdown content rendered as a child panel.
"""

from __future__ import annotations

from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id


@ContentRendererRegistry.register("tabs", "default", description="Tabbed content renderer")
class TabsRenderer(ContentRenderer):
    """Renders tabbed content to A2UI Tabs components.

    Expected input format:
        {
            "tabs": [
                {"label": "Overview", "content": "Markdown content..."},
                {"label": "Details", "content": "More content..."}
            ],
            "title": "Optional Title"
        }

    - tabs: Non-empty list of tab dicts, each with "label" and "content" (required)
    - title: Optional title displayed above the tabs
    """

    @property
    def content_type(self) -> str:
        return "tabs"

    def detect(self, content: Any) -> bool:
        """Detect if content is tabbed data.

        Matches dicts with "tabs" key containing a non-empty list of dicts,
        each having a "label" key.
        """
        if not isinstance(content, dict):
            return False
        tabs = content.get("tabs")
        if not isinstance(tabs, list) or len(tabs) == 0:
            return False
        return all(isinstance(t, dict) and "label" in t for t in tabs)

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert tabbed content to A2UI Tabs component with children."""
        tabs = content["tabs"]
        title = content.get("title")

        components: list[A2UIComponent] = []

        # Optional title as Text component
        if title:
            components.append(
                A2UIComponent(
                    id=gen_id("tabs-title"),
                    component="Text",
                    properties={"text": title, "variant": "h4"},
                )
            )

        # Build child components for each tab panel
        child_ids: list[str] = []
        child_components: list[A2UIComponent] = []

        for tab in tabs:
            tab_content = tab.get("content", "")
            child_id = gen_id("tab-panel")
            child_ids.append(child_id)
            child_components.append(
                A2UIComponent(
                    id=child_id,
                    component="ObMarkdown",
                    properties={"content": tab_content},
                )
            )

        # Tabs component
        tabs_id = gen_id("tabs")
        tab_defs = [{"label": t["label"]} for t in tabs]

        components.append(
            A2UIComponent(
                id=tabs_id,
                component="Tabs",
                properties={
                    "tabs": tab_defs,
                    "children": child_ids,
                },
            )
        )
        components.extend(child_components)

        return components
