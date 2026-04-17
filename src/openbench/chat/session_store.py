"""Persistent storage for ChatSession objects.

Defines the ``SessionStore`` ABC that chat applications plug in to
persist full ChatSessions (UI-level messages with surfaces and
attachments). Distinct from ``MemoryStore`` which stores LLM-level
``Message`` objects.

A default SQLite-backed implementation lives in
``openbench.chat.stores.sqlite``.

Example:
    >>> from openbench.chat.stores.sqlite import SQLiteSessionStore
    >>> store = SQLiteSessionStore(".openbench/sessions.db")
    >>> store.save(session)
    >>> reloaded = store.load(session.session_id)
    >>> summaries = store.list(limit=20)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from openbench.chat.session import ChatSession


@dataclass
class SessionSummary:
    """Lightweight session metadata for list views.

    Returned by ``SessionStore.list()`` without loading full message
    history — keeps sidebar renders fast for users with many sessions.

    Attributes:
        session_id: Unique session identifier.
        title: Human-readable title.
        created_at: UTC timestamp of session creation.
        updated_at: UTC timestamp of last message added.
        message_count: Total messages in the session.
        preview: Truncated first user message (for sidebar display).
    """

    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str = ""

    def to_dict(self) -> dict:
        """Serialize to dict (ISO-8601 timestamps)."""
        return {
            "sessionId": self.session_id,
            "title": self.title,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "messageCount": self.message_count,
            "preview": self.preview,
        }


class SessionStore(ABC):
    """Persist and retrieve full ChatSession objects.

    Contract:
    - ``save`` is idempotent (re-saving updates the session).
    - ``load`` returns None for unknown session_id (not raise).
    - ``list`` orders by ``updated_at`` descending.
    - ``delete`` is idempotent (no-op for unknown session_id).
    """

    @abstractmethod
    def save(self, session: ChatSession) -> None:
        """Persist a session. Overwrites existing data for the same id.

        Args:
            session: The ChatSession to persist.
        """

    @abstractmethod
    def load(self, session_id: str) -> ChatSession | None:
        """Load a session by id.

        Args:
            session_id: The session id to load.

        Returns:
            The ChatSession, or None if not found.
        """

    @abstractmethod
    def list(self, limit: int = 50, offset: int = 0) -> list[SessionSummary]:
        """List session summaries, most-recently-updated first.

        Args:
            limit: Maximum number of summaries to return.
            offset: Number of summaries to skip (for pagination).

        Returns:
            List of ``SessionSummary`` ordered by ``updated_at`` desc.
        """

    @abstractmethod
    def delete(self, session_id: str) -> None:
        """Delete a session. No-op if the id is unknown.

        Args:
            session_id: The session id to delete.
        """

    def search(self, query: str, limit: int = 20) -> list[SessionSummary]:
        """Full-text search across sessions.

        Default: no-op (returns empty list). Backends that support
        search override this.

        Args:
            query: Search query string.
            limit: Maximum results to return.

        Returns:
            Matching session summaries (empty by default).
        """
        return []
