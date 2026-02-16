"""
Callout content renderer.

Converts callout data dicts to A2UI ObCallout components.
Supports variant-based styling (default, info, success, warning).
"""

from __future__ import annotations

import uuid
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry

VALID_VARIANTS = ("default", "info", "success", "warning")


@ContentRendererRegistry.register("callout", "default", description="Callout box renderer")
class CalloutRenderer(ContentRenderer):
    """Renders callout data to ObCallout A2UI components.

    Expected input format:
        {
            "calloutContent": "Important note about data accuracy.",
            "variant": "warning",
            "title": "Warning"
        }

    - calloutContent: Non-empty string of content (required)
    - variant: One of default, info, success, warning (default: "default")
    - title: Optional bold title
    """

    @property
    def content_type(self) -> str:
        return "callout"

    def detect(self, content: Any) -> bool:
        """Detect if content is callout data.

        Matches dicts with "calloutContent" key containing a non-empty string.
        """
        if not isinstance(content, dict):
            return False
        callout_content = content.get("calloutContent")
        return isinstance(callout_content, str) and len(callout_content) > 0

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert callout data to ObCallout component."""
        callout_content = content["calloutContent"]
        variant = content.get("variant", "default")
        title = content.get("title", "")

        # Validate variant, default to "default" if invalid
        if variant not in VALID_VARIANTS:
            variant = "default"

        callout_props: dict[str, Any] = {
            "content": callout_content,
            "variant": variant,
        }
        if title:
            callout_props["title"] = title

        return [
            A2UIComponent(
                id=_gen_id("callout"),
                component="ObCallout",
                properties=callout_props,
            )
        ]


def _gen_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
