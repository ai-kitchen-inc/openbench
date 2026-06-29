"""
Modal content renderer.

Converts modal data dicts to A2UI Modal components with ObMarkdown children.
Renders content inside a centered overlay panel.
"""

from __future__ import annotations

from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id


@ContentRendererRegistry.register("modal", "default", description="Modal overlay renderer")
class ModalRenderer(ContentRenderer):
    """Renders modal content to A2UI Modal components.

    Expected input format:
        {
            "modalContent": "Markdown content for the modal body",
            "modalTitle": "Optional Modal Title"
        }

    - modalContent: Non-empty string of markdown content (required)
    - modalTitle: Optional title displayed in the modal header
    """

    @property
    def content_type(self) -> str:
        return "modal"

    def detect(self, content: Any) -> bool:
        """Detect if content is modal data.

        Matches dicts with "modalContent" key containing a non-empty string.
        """
        if not isinstance(content, dict):
            return False
        modal_content = content.get("modalContent")
        return isinstance(modal_content, str) and len(modal_content) > 0

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert modal data to A2UI Modal component with ObMarkdown child."""
        modal_content = content["modalContent"]
        modal_title = content.get("modalTitle", "")

        components: list[A2UIComponent] = []

        # Child: ObMarkdown with modal body content
        child_id = gen_id("modal-body")
        child = A2UIComponent(
            id=child_id,
            component="ObMarkdown",
            properties={"content": modal_content},
        )

        # Modal component
        modal_id = gen_id("modal")
        modal_props: dict[str, Any] = {
            "open": True,
            "children": [child_id],
        }
        if modal_title:
            modal_props["title"] = modal_title

        components.append(A2UIComponent(id=modal_id, component="Modal", properties=modal_props))
        components.append(child)

        return components
