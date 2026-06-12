"""
Chat session and message management.

Provides:
- ChatMessage: Extended message with A2UI surface data
- Attachment: File/media attachment
- ChatSession: Manages conversation history and state
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MessageRole(Enum):
    """Role in chat conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class Attachment:
    """File or media attachment on a chat message."""

    id: str
    type: str  # "file", "audio", "video", "image"
    name: str
    url: str
    mime_type: str
    size_bytes: int | None = None
    extracted_text: str | None = None
    path: str | None = None  # Absolute disk path (set by server for tool access)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        result: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "url": self.url,
            "mimeType": self.mime_type,
        }
        if self.size_bytes is not None:
            result["sizeBytes"] = self.size_bytes
        if self.extracted_text is not None:
            result["extractedText"] = self.extracted_text
        if self.path is not None:
            result["path"] = self.path
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attachment:
        """Deserialize from dict."""
        return cls(
            id=data["id"],
            type=data["type"],
            name=data["name"],
            url=data["url"],
            mime_type=data["mimeType"],
            size_bytes=data.get("sizeBytes"),
            extracted_text=data.get("extractedText"),
            path=data.get("path"),
        )


@dataclass
class ChatMessage:
    """A message in a chat conversation, with optional A2UI surfaces."""

    id: str
    role: MessageRole
    content: str
    surfaces: list[dict[str, Any]] | None = None
    attachments: list[Attachment] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        result: dict[str, Any] = {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.surfaces:
            result["surfaces"] = self.surfaces
        if self.attachments:
            result["attachments"] = [a.to_dict() for a in self.attachments]
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:
        """Deserialize from dict."""
        attachments = None
        if "attachments" in data:
            attachments = [Attachment.from_dict(a) for a in data["attachments"]]

        return cls(
            id=data["id"],
            role=MessageRole(data["role"]),
            content=data["content"],
            surfaces=data.get("surfaces"),
            attachments=attachments,
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {}),
        )


class ChatSession:
    """Manages conversation history and state for a chat session.

    Provides message management, context windowing, and serialization.
    """

    def __init__(
        self,
        session_id: str | None = None,
        title: str = "New Chat",
    ):
        self.session_id = session_id or str(uuid.uuid4())
        self.title = title
        self.messages: list[ChatMessage] = []
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def add_user_message(
        self,
        content: str,
        attachments: list[Attachment] | None = None,
    ) -> ChatMessage:
        """Add a user message to the session."""
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=content,
            attachments=attachments,
        )
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def add_assistant_message(
        self,
        content: str,
        surfaces: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """Add an assistant message to the session."""
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            content=content,
            surfaces=surfaces,
            metadata=metadata or {},
        )
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def add_system_message(self, content: str) -> ChatMessage:
        """Add a system message to the session."""
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            role=MessageRole.SYSTEM,
            content=content,
        )
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def get_context_window(self, max_messages: int = 50) -> list[ChatMessage]:
        """Get recent messages for LLM context window.

        Preserves system messages at the start, then takes the most recent
        non-system messages up to max_messages.
        """
        system_msgs = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in self.messages if m.role != MessageRole.SYSTEM]

        remaining = max_messages - len(system_msgs)
        recent = non_system[-remaining:] if remaining > 0 else []

        return system_msgs + recent

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "sessionId": self.session_id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatSession:
        """Deserialize from dict."""
        session = cls(
            session_id=data["sessionId"],
            title=data.get("title", "New Chat"),
        )
        session.messages = [ChatMessage.from_dict(m) for m in data.get("messages", [])]
        session.created_at = datetime.fromisoformat(data["createdAt"])
        session.updated_at = datetime.fromisoformat(data["updatedAt"])
        return session

    def __len__(self) -> int:
        """Return message count.

        Warning: Empty sessions return 0 (falsy). Use ``x is not None``
        instead of ``x or default`` when accepting optional ChatSession.
        """
        return len(self.messages)

    def __repr__(self) -> str:
        return f"ChatSession(id={self.session_id!r}, messages={len(self.messages)})"
