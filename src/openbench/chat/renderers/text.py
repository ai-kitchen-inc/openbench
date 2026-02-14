"""
Text content renderer.

Converts plain text and markdown strings to A2UI Text and ObMarkdown components.
Handles semantic variants (h1-h5, body, caption) via markdown heading detection.
"""
from __future__ import annotations


import re
import uuid
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry


@ContentRendererRegistry.register("text", "default", description="Text and markdown renderer")
class TextRenderer(ContentRenderer):
    """Renders text/markdown content to A2UI components.

    Simple text -> Text component with body variant.
    Markdown with headings -> multiple Text components with semantic variants.
    Complex markdown (code blocks, lists, links) -> ObMarkdown component.
    """

    @property
    def content_type(self) -> str:
        return "text"

    def detect(self, content: Any) -> bool:
        """Detect if content is text/markdown."""
        return isinstance(content, str) and len(content.strip()) > 0

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert text content to A2UI components.

        Strategy:
        - If content has complex markdown (code fences, tables, links, images),
          use a single ObMarkdown component.
        - If content is simple text (possibly with headings), split into
          individual Text components with semantic variants.
        """
        text = str(content).strip()

        if self._is_complex_markdown(text):
            return self._render_markdown(text)
        else:
            return self._render_simple_text(text)

    def _is_complex_markdown(self, text: str) -> bool:
        """Check if text contains complex markdown requiring ObMarkdown."""
        complex_patterns = [
            r"```",           # Code fences
            r"\|.*\|.*\|",   # Tables
            r"!\[",          # Images
            r"\[.*\]\(.*\)", # Links
            r"^\s*[-*+]\s",  # Unordered lists
            r"^\s*\d+\.\s",  # Ordered lists
            r"^\s*>",        # Blockquotes
            r"\$\$",         # Display math ($$...$$)
            r"(?<!\$)\$(?!\$|\d).+?\$(?!\$)",  # Inline math ($...$), not $$ or currency ($digits)
            r"\\\[",         # Display math (\[...\])
            r"\\\(",         # Inline math (\(...\))
        ]
        for pattern in complex_patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True
        return False

    def _render_markdown(self, text: str) -> list[A2UIComponent]:
        """Render complex markdown as ObMarkdown component."""
        return [
            A2UIComponent(
                id=_gen_id("md"),
                component="ObMarkdown",
                properties={"content": text},
            )
        ]

    def _render_simple_text(self, text: str) -> list[A2UIComponent]:
        """Render simple text as Text components with semantic variants."""
        components: list[A2UIComponent] = []
        lines = text.split("\n")

        # Accumulate body lines between headings
        body_buffer: list[str] = []

        for line in lines:
            heading_match = re.match(r"^(#{1,5})\s+(.+)$", line)
            if heading_match:
                # Flush body buffer
                if body_buffer:
                    components.append(self._make_text_component(
                        "\n".join(body_buffer).strip(), "body"
                    ))
                    body_buffer = []

                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                variant = f"h{level}"
                components.append(self._make_text_component(heading_text, variant))
            else:
                body_buffer.append(line)

        # Flush remaining body
        if body_buffer:
            body_text = "\n".join(body_buffer).strip()
            if body_text:
                components.append(self._make_text_component(body_text, "body"))

        # Fallback: empty content
        if not components:
            components.append(self._make_text_component(text, "body"))

        return components

    def _make_text_component(self, text: str, variant: str) -> A2UIComponent:
        """Create a Text A2UI component."""
        return A2UIComponent(
            id=_gen_id("txt"),
            component="Text",
            properties={"text": text, "variant": variant},
        )


def _gen_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
