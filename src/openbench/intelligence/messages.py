"""Conversation message primitives for OpenBench agents.

Provides :class:`MessageRole` and :class:`Message` — the provider-neutral
representation of a single conversation turn. Extracted from
``intelligence/base.py`` so the message model lives on its own; ``base`` still
re-exports both names for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.core.abstractions import MediaContent


class MessageRole(Enum):
    """Role in conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """A message in agent conversation."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    raw_content: Any = field(default=None, repr=False)
    media: list[MediaContent] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to LLM-compatible format."""
        result = {"role": self.role.value, "content": self.content}
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.raw_content is not None:
            result["raw_content"] = self.raw_content
        if self.media:
            # Provider-neutral media references; each LLMProvider translates
            # these into its own multimodal format in _convert_messages.
            result["media"] = [m.to_dict() for m in self.media]
        return result
