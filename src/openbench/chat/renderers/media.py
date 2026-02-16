"""
Media content renderer.

Converts media data dicts to A2UI Image, Video, and AudioPlayer components.
Supports: image, video, audio media types.
"""

from __future__ import annotations

import uuid
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry

VALID_MEDIA_TYPES = ("image", "video", "audio")

# Maps mediaType to A2UI component name
_COMPONENT_MAP = {
    "image": "Image",
    "video": "Video",
    "audio": "AudioPlayer",
}


@ContentRendererRegistry.register("media", "default", description="Media content renderer")
class MediaRenderer(ContentRenderer):
    """Renders media data to Image, Video, or AudioPlayer A2UI components.

    Expected input format:
        {"mediaType": "image", "src": "https://...", "alt": "description"}
        {"mediaType": "video", "src": "https://...", "title": "My Video"}
        {"mediaType": "audio", "src": "https://...", "title": "Podcast"}

    - mediaType: One of image, video, audio (required)
    - src: Media URL (required)
    - title: Optional title displayed above the media
    - Image-specific: alt, width, height
    - Video-specific: poster, autoplay, width, height
    - Audio-specific: autoplay
    """

    @property
    def content_type(self) -> str:
        return "media"

    def detect(self, content: Any) -> bool:
        """Detect if content is media data.

        Matches dicts with "mediaType" key whose value is a valid media type,
        and a "src" key.
        """
        if not isinstance(content, dict):
            return False
        return content.get("mediaType") in VALID_MEDIA_TYPES and "src" in content

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert media data to the appropriate A2UI component."""
        media_type = content["mediaType"]
        src = content["src"]
        title = content.get("title")

        components: list[A2UIComponent] = []

        # Optional title as Text component
        if title:
            components.append(
                A2UIComponent(
                    id=_gen_id("media-title"),
                    component="Text",
                    properties={"text": title, "variant": "h4"},
                )
            )

        # Build component based on media type
        component_name = _COMPONENT_MAP[media_type]
        props: dict[str, Any] = {"src": src}

        if media_type == "image":
            if "alt" in content:
                props["alt"] = content["alt"]
            elif "caption" in content:
                props["alt"] = content["caption"]
            if "width" in content:
                props["width"] = content["width"]
            if "height" in content:
                props["height"] = content["height"]

        elif media_type == "video":
            if "title" in content:
                props["title"] = content["title"]
            if "poster" in content:
                props["poster"] = content["poster"]
            if "autoplay" in content:
                props["autoplay"] = content["autoplay"]
            if "width" in content:
                props["width"] = content["width"]
            if "height" in content:
                props["height"] = content["height"]

        elif media_type == "audio":
            if "title" in content:
                props["title"] = content["title"]
            if "autoplay" in content:
                props["autoplay"] = content["autoplay"]

        components.append(
            A2UIComponent(
                id=_gen_id(media_type),
                component=component_name,
                properties=props,
            )
        )

        return components


def _gen_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
