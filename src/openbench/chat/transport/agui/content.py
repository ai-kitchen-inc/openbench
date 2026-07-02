"""Request-body content/attachment extraction for the AG-UI handler."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class _ContentExtractionMixin:
    """Mixin for AGUIHandler; not instantiated directly."""

    def _extract_content(self, body: dict[str, Any]) -> tuple[str, list | None]:
        """Extract content and attachments from request body.

        Accepts both AG-UI RunAgentInput format (messages array) and
        OpenBench format ({content: "..."}).

        Args:
            body: Request body dict.

        Returns:
            Tuple of (content string, optional attachments list).
        """
        # AG-UI format: messages array with role-based messages
        messages = body.get("messages")
        if messages and isinstance(messages, list):
            # Find the last user message
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    break
            else:
                content = ""

            # Attachments from forwardedProps
            forwarded = body.get("forwardedProps") or {}
            raw_attachments = forwarded.get("attachments")
            attachments = self._coerce_attachments(raw_attachments)
            return content, attachments

        # OpenBench format: {content: "...", attachments: [...]}
        content = body.get("content", "")
        raw_attachments = body.get("attachments")
        attachments = self._coerce_attachments(raw_attachments)
        return content, attachments

    def _coerce_attachments(self, raw: Any) -> list | None:
        """Coerce raw attachment data to Attachment objects or None."""
        if not raw:
            return None
        return self.engine._coerce_attachments(raw) if raw else None
