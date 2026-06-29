"""Module-level defaults for the chat engine: abort placeholder + renderer bootstrap."""

from __future__ import annotations

import logging
import os

from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry

logger = logging.getLogger(__name__)


_PLACEHOLDER_TURN_INTERRUPTED = "⚠️ Turn interrupted. Please retry."


def _placeholder_on_abort_enabled() -> bool:
    """Gate the aborted-turn placeholder via env var.

    Default ``"1"`` (on). Set ``OPENBENCH_PLACEHOLDER_ON_ABORT=0`` to
    suppress — e.g. test suites that want the session to end with a bare
    user message instead of the placeholder.
    """
    flag = os.environ.get("OPENBENCH_PLACEHOLDER_ON_ABORT", "1").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _get_default_renderers() -> list[ContentRenderer]:
    """Create default renderer instances from registry."""
    renderers: list[ContentRenderer] = []
    for key in ContentRendererRegistry.list_plugins():
        try:
            plugin_type, provider = key.split(":", 1)
            renderer = ContentRendererRegistry.create(plugin_type, provider)
            renderers.append(renderer)
        except Exception:
            logger.warning(f"Failed to create renderer: {key}")
    return renderers
