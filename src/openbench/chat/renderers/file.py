"""
File content renderer.

Converts file metadata dicts to A2UI ObFileCard components.
"""

from __future__ import annotations

from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id


@ContentRendererRegistry.register("file", "default", description="File preview renderer")
class FileRenderer(ContentRenderer):
    """Renders file metadata to ObFileCard A2UI components.

    Expected input format:
        {"name": "report.pdf", "url": "https://...", "size": 2048, "mimeType": "application/pdf"}

    Or a list of such dicts for multiple files.

    Optional fields:
    - previewUrl: URL for file preview/thumbnail
    - size: File size in bytes
    - mimeType: MIME type string
    """

    @property
    def content_type(self) -> str:
        return "file"

    def detect(self, content: Any) -> bool:
        """Detect if content is file metadata.

        Matches dicts with "name" and "url" keys, or lists of such dicts.
        """
        if isinstance(content, dict):
            return "name" in content and "url" in content
        if isinstance(content, list) and len(content) > 0:
            return all(
                isinstance(item, dict) and "name" in item and "url" in item for item in content
            )
        return False

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert file metadata to ObFileCard components."""
        if isinstance(content, dict):
            return [self._render_single(content)]
        if isinstance(content, list):
            return [self._render_single(item) for item in content]
        return []

    def _render_single(self, file_data: dict[str, Any]) -> A2UIComponent:
        """Render a single file to an ObFileCard component."""
        props: dict[str, Any] = {
            "fileName": file_data["name"],
            "fileUrl": file_data["url"],
        }

        if "size" in file_data:
            props["fileSize"] = file_data["size"]
        if "mimeType" in file_data:
            props["mimeType"] = file_data["mimeType"]
        if "previewUrl" in file_data:
            props["previewUrl"] = file_data["previewUrl"]
        # Propagate the "external" flag when set by a cloud-backed
        # producer (e.g. Drive ``webViewLink``) so the frontend opens
        # the URL in a new tab without forcing a download.
        if file_data.get("external"):
            props["external"] = True

        return A2UIComponent(
            id=gen_id("file"),
            component="ObFileCard",
            properties=props,
        )
