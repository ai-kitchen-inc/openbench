"""Persistent memory for agents.

Provides:
- MemoryStore: Abstract storage backend for conversation persistence
- SQLiteMemoryStore: SQLite-backed implementation
- PersistentMemory: AgentMemory subclass with automatic persistence

Used by BaseAgent when ``memory_store`` is provided to persist conversations
across sessions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from openbench.intelligence.base import AgentMemory, Message, MessageRole

logger = logging.getLogger(__name__)


class MemoryStore(ABC):
    """Abstract memory storage backend."""

    @abstractmethod
    def save(self, session_id: str, messages: list[Message]) -> None:
        """Persist messages for a session.

        Args:
            session_id: Unique session identifier.
            messages: Messages to save.
        """

    @abstractmethod
    def load(self, session_id: str) -> list[Message]:
        """Load messages for a session.

        Args:
            session_id: Unique session identifier.

        Returns:
            List of messages for the session, ordered by insertion time.
        """

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[Message]:
        """Search across all sessions for matching messages.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching messages.
        """

    @abstractmethod
    def list_sessions(self) -> list[str]:
        """List all session IDs.

        Returns:
            List of session IDs.
        """

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete all messages for a session.

        Args:
            session_id: Session to delete.
        """


class SQLiteMemoryStore(MemoryStore):
    """SQLite-backed persistent memory store.

    Stores conversation messages in a local SQLite database file.
    Thread-safe via SQLite's built-in locking.

    Example:
        >>> store = SQLiteMemoryStore("memory.db")
        >>> store.save("session-1", [Message(role=MessageRole.USER, content="Hello")])
        >>> messages = store.load("session-1")
    """

    def __init__(self, db_path: str = ".openbench/memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    name TEXT,
                    tool_call_id TEXT,
                    tool_calls TEXT,
                    timestamp TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id)")
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection."""
        return sqlite3.connect(self.db_path)

    def save(self, session_id: str, messages: list[Message]) -> None:
        """Persist messages for a session."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            for msg in messages:
                tool_calls_json = json.dumps(msg.tool_calls) if msg.tool_calls else None
                conn.execute(
                    "INSERT INTO messages "
                    "(session_id, role, content, name, tool_call_id, tool_calls, timestamp, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        msg.role.value,
                        msg.content,
                        msg.name,
                        msg.tool_call_id,
                        tool_calls_json,
                        now,
                        None,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def load(self, session_id: str) -> list[Message]:
        """Load messages for a session."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT role, content, name, tool_call_id, tool_calls "
                "FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            return [
                Message(
                    role=MessageRole(row[0]),
                    content=row[1],
                    name=row[2],
                    tool_call_id=row[3],
                    tool_calls=json.loads(row[4]) if row[4] else None,
                )
                for row in rows
            ]
        finally:
            conn.close()

    def search(self, query: str, limit: int = 5) -> list[Message]:
        """Search messages across all sessions using keyword matching."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT role, content, name, tool_call_id, tool_calls "
                "FROM messages WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [
                Message(
                    role=MessageRole(row[0]),
                    content=row[1],
                    name=row[2],
                    tool_call_id=row[3],
                    tool_calls=json.loads(row[4]) if row[4] else None,
                )
                for row in rows
            ]
        finally:
            conn.close()

    def list_sessions(self) -> list[str]:
        """List all session IDs."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM messages ORDER BY session_id"
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> None:
        """Delete all messages for a session."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()


class PersistentMemory(AgentMemory):
    """AgentMemory with automatic persistence.

    Wraps AgentMemory so every ``add()`` call is automatically persisted
    to the underlying MemoryStore. Previous messages are loaded on init.

    Example:
        >>> store = SQLiteMemoryStore("memory.db")
        >>> memory = PersistentMemory(store=store, session_id="chat-1")
        >>> memory.add_user("Hello")  # Persisted automatically
        >>>
        >>> # Later, in a new process:
        >>> memory2 = PersistentMemory(store=store, session_id="chat-1")
        >>> memory2.get_messages()  # Contains "Hello" from before
    """

    def __init__(
        self,
        store: MemoryStore,
        session_id: str,
        max_messages: int = 100,
        max_tokens: int | None = None,
    ):
        super().__init__(max_messages=max_messages, max_tokens=max_tokens)
        self.store = store
        self.session_id = session_id
        # Load previous conversation
        self.messages = self.store.load(session_id)

    def add(self, role: MessageRole, content: str, **kwargs: Any) -> None:
        """Add message and persist to store."""
        super().add(role, content, **kwargs)
        # Persist the newly added message
        self.store.save(self.session_id, [self.messages[-1]])

    def search_history(self, query: str, limit: int = 5) -> list[Message]:
        """Search across all past sessions.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching messages from any session.
        """
        return self.store.search(query, limit)

    def clear(self) -> None:
        """Clear in-memory messages and delete from store."""
        super().clear()
        self.store.delete_session(self.session_id)
