"""
Code block content renderer.

Converts code data dicts to A2UI ObCodeBlock components.
Supports any language with optional line numbers and max height.
"""

from __future__ import annotations

from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id


@ContentRendererRegistry.register("code", "default", description="Code block renderer")
class CodeRenderer(ContentRenderer):
    """Renders code data to ObCodeBlock A2UI components.

    Expected input format:
        {"code": "print('hello')", "language": "python"}

    - code: Source code string (required)
    - language: Programming language for syntax highlighting (required for detect)
    - title: Optional title displayed above the code block
    - showLineNumbers: Optional boolean (default True)
    - maxHeight: Optional max height (default "400px")
    """

    @property
    def content_type(self) -> str:
        return "code"

    def detect(self, content: Any) -> bool:
        """Detect if content is code block data.

        Matches dicts with both "code" and "language" keys.
        """
        if not isinstance(content, dict):
            return False
        return "code" in content and "language" in content

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert code data to ObCodeBlock component."""
        code = content["code"]
        language = content["language"]
        title = content.get("title")
        show_line_numbers = content.get("showLineNumbers", True)
        max_height = content.get("maxHeight", "400px")

        components: list[A2UIComponent] = []

        # Optional title as Text component
        if title:
            components.append(
                A2UIComponent(
                    id=gen_id("code-title"),
                    component="Text",
                    properties={"text": title, "variant": "h4"},
                )
            )

        # ObCodeBlock component
        components.append(
            A2UIComponent(
                id=gen_id("code"),
                component="ObCodeBlock",
                properties={
                    "code": code,
                    "language": language,
                    "showLineNumbers": show_line_numbers,
                    "maxHeight": max_height,
                },
            )
        )

        return components
