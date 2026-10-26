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


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO timestamp, falling back to now() on missing/invalid input."""
    try:
        return datetime.fromisoformat(value) if value else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


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
        """Deserialize from dict, tolerating partial corruption.

        Missing/invalid optional fields are defaulted rather than raised so a
        single malformed message never fails the whole history load. Bad
        individual attachments are dropped. Raises ``ValueError`` only when the
        message has no usable role.
        """
        raw_role = data.get("role")
        try:
            role = MessageRole(raw_role)
        except ValueError as exc:
            raise ValueError(f"unknown message role: {raw_role!r}") from exc

        attachments: list[Attachment] | None = None
        if data.get("attachments"):
            parsed: list[Attachment] = []
            for a in data["attachments"]:
                try:
                    parsed.append(Attachment.from_dict(a))
                except Exception as att_exc:  # drop bad attachment, keep message
                    logger.warning("Dropping malformed attachment: %s", att_exc)
            attachments = parsed or None

        raw_ts = data.get("timestamp")
        try:
            timestamp = (
                datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(timezone.utc)
            )
        except (TypeError, ValueError):
            timestamp = datetime.now(timezone.utc)

        return cls(
            id=data.get("id") or str(uuid.uuid4()),
            role=role,
            content=data.get("content") or "",
            surfaces=data.get("surfaces"),
            attachments=attachments,
            timestamp=timestamp,
            metadata=data.get("metadata") or {},
        )


class ChatSession:
    """Manages conversation history and state for a chat session.

    Provides message management, context windowing, and serialization.
    """

    def __init__(
        self,
        session_id: str | None = None,
        title: str = "New Chat",
        metadata: dict[str, Any] | None = None,
    ):
        self.session_id = session_id or str(uuid.uuid4())
        self.title = title
        self.messages: list[ChatMessage] = []
        # Per-session preferences (e.g. the selected agent id). Serialized
        # only when non-empty so stored rows and their consumers are
        # unaffected until a preference is actually set.
        self.metadata: dict[str, Any] = metadata or {}
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
        result = {
            "sessionId": self.session_id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatSession:
        """Deserialize from dict, tolerating partial corruption.

        Skips individual messages that fail to parse (logging a warning) so the
        session still loads with whatever is valid, and defaults missing
        top-level fields instead of raising — a corrupt row should degrade, not
        500 the history endpoint.
        """
        raw_metadata = data.get("metadata")
        session = cls(
            session_id=data.get("sessionId") or str(uuid.uuid4()),
            title=data.get("title", "New Chat"),
            metadata=raw_metadata if isinstance(raw_metadata, dict) else None,
        )

        messages: list[ChatMessage] = []
        for raw in data.get("messages", []):
            try:
                messages.append(ChatMessage.from_dict(raw))
            except Exception as exc:  # skip the bad message, keep the rest
                logger.warning(
                    "Skipping malformed message in session %s: %s",
                    session.session_id,
                    exc,
                )
        session.messages = messages

        session.created_at = _parse_dt(data.get("createdAt"))
        session.updated_at = _parse_dt(data.get("updatedAt"))
        return session

    def __len__(self) -> int:
        """Return message count.

        Warning: Empty sessions return 0 (falsy). Use ``x is not None``
        instead of ``x or default`` when accepting optional ChatSession.
        """
        return len(self.messages)

    def __repr__(self) -> str:
        return f"ChatSession(id={self.session_id!r}, messages={len(self.messages)})"
