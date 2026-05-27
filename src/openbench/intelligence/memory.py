"""Persistent memory for agents.

Provides:
- MemoryStore: Abstract storage backend for conversation persistence
- SQLiteMemoryStore: SQLite-backed implementation
- PersistentMemory: AgentMemory subclass with automatic persistence

Used by BaseAgent when ``memory_store`` is provided to persist conversations
across sessions.

Pillar placement (see ``docs/MENTAL_MODEL.md``): ``MemoryStore`` is
**plumbing under the Agentic pillar**, not a pillar of its own.
Hot-path per-turn persistence with transactional semantics — stays
Protocol-based ABC, not MCP.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from openbench.intelligence.base import AgentMemory, Message, MessageRole

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _turn_transaction_enabled() -> bool:
    """Gate the per-turn memory transaction via env var.

    Default ``"1"`` (on). Set ``OPENBENCH_TURN_TRANSACTION=0`` to revert
    to per-message autocommit — the legacy behaviour, useful as a
    rollback lever if the transaction introduces unexpected issues.
    """
    flag = os.environ.get("OPENBENCH_TURN_TRANSACTION", "1").strip().lower()
    return flag in ("1", "true", "yes", "on")


class MemoryStore(ABC):
    """Public ABC for backends that persist agent conversation memory.

    Part of OpenBench's stable public API surface — third-party
    backends (Postgres, MySQL, Redis, S3, Firestore, in-memory for
    tests, …) implement this ABC to plug into the storage protocol.
    Same extensibility commitment as :class:`LLMProvider`,
    :class:`DataStore`, :class:`SessionStore`, :class:`FileStore`,
    :class:`ScratchpadStore`, and :class:`PersonaSource`.

    **Stability guarantee**: additive-only across minor versions. New
    optional methods may be added with sensible defaults; existing
    signatures never break within a minor version. Third-party
    implementations are safe to build against this ABC across patch
    and minor bumps.

    **Validating your impl**: use
    :class:`openbench.testing.MemoryStoreContract` — inherit, override
    ``make_store``, and get a parametrized suite of conformance tests
    for free. The SDK's own SQLite + Drive impls use the same base.

    **Method semantics**:

    - :meth:`save` — **append** ``messages`` to the session, preserving
      existing messages. This matches the current PersistentMemory
      hot-path (one message per add). Backends with blob semantics
      (e.g. Drive) must read-modify-write internally; Layer 2a's
      ``memory.turn()`` context batches writes so blob-backed impls
      pay at most one write per turn.
    - :meth:`load` — return the full ordered message history for
      ``session_id``, or an empty list if the session is unknown.
    - :meth:`search` — full-text or keyword search across sessions.
      Default returns empty; backends without natural search support
      should keep the default.
    - :meth:`list_sessions` — enumerate known session ids.
    - :meth:`delete_session` — remove the session entirely.
    - :meth:`delete_tail` — remove the last N messages. Default
      implementation reloads the session and re-saves the head;
      backends should override for efficiency when possible.
    """

    @abstractmethod
    def save(self, session_id: str, messages: list[Message]) -> None:
        """Append ``messages`` to ``session_id``'s history.

        Args:
            session_id: Unique session identifier.
            messages: Messages to append. Order is preserved.

        Behavioral note: this is **append**, not replace. To replace a
        full session, call :meth:`delete_session` followed by
        :meth:`save` with the new list. :class:`PersistentMemory` calls
        ``save`` per message (outside a turn) or once with the turn
        buffer (inside a turn).
        """

    @abstractmethod
    def load(self, session_id: str) -> list[Message]:
        """Return ``session_id``'s message history in insertion order.

        Returns empty list for unknown sessions — never raises.
        """

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[Message]:
        """Search across all sessions for matching messages.

        Default contract for backends without native search: return an
        empty list and optionally log a warning. Implementers should
        override only when natural search support exists (SQLite FTS,
        Postgres tsvector, Elasticsearch, …).
        """

    @abstractmethod
    def list_sessions(self) -> list[str]:
        """List all session IDs known to this store."""

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete all messages for a session. Idempotent."""

    def delete_tail(self, session_id: str, count: int) -> None:
        """Delete the last ``count`` messages for a session.

        Used by :meth:`PersistentMemory.truncate_to` to roll back a
        failed agent turn. The default implementation reloads the full
        session, drops the tail in-memory, then replaces the session in
        the store — correct but inefficient for large sessions.
        Subclasses should override with a targeted delete when possible.

        Args:
            session_id: Session to truncate.
            count: Number of trailing messages to delete. Values <= 0
                are a no-op; values >= session length delete the whole
                session.
        """
        if count <= 0:
            return
        existing = self.load(session_id)
        if count >= len(existing):
            self.delete_session(session_id)
            return
        kept = existing[: len(existing) - count]
        self.delete_session(session_id)
        if kept:
            self.save(session_id, kept)


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
        """Initialize database schema, with idempotent upgrades.

        ``CREATE TABLE IF NOT EXISTS`` handles fresh installs. For
        deployments upgrading from a pre-RFC-UNIFIED-MEMORY-STORAGE
        version, we run ``ADD COLUMN`` inside a try/except per new
        column — SQLite raises ``OperationalError`` on duplicate column
        which we swallow. This is safe on any SQLite ≥ 3.35 (Python
        3.10+ stdlib ships 3.31+, Python 3.12+ ships 3.40+).

        New columns (additive, never used by Phase 1, reserved for
        Phase 2 Drive backend):
        - ``pending_sync INTEGER DEFAULT 0`` — flag for rows queued for
          Drive sync when the Drive backend is offline.
        - ``drive_etag TEXT`` — last-seen ETag of the Drive blob for
          this session, enabling optimistic-locking reconciliation.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
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
                """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id)")

            # Phase 1 additive schema upgrade — idempotent ALTER TABLE.
            # Each column added inside its own try/except so the second
            # start-up (both columns already present) is a silent no-op.
            for alter in (
                "ALTER TABLE messages ADD COLUMN pending_sync INTEGER DEFAULT 0",
                "ALTER TABLE messages ADD COLUMN drive_etag TEXT",
            ):
                try:
                    conn.execute(alter)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
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

    def delete_tail(self, session_id: str, count: int) -> None:
        """Delete the ``count`` most-recently-inserted messages for a session.

        Uses a single SQL DELETE targeting the highest ``id`` rows for the
        session — O(count) in SQLite. Overrides the base load/save fallback.
        """
        if count <= 0:
            return
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM messages WHERE id IN ("
                "SELECT id FROM messages WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?"
                ")",
                (session_id, count),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Pending-sync queue API (RFC-UNIFIED-MEMORY-STORAGE Phase 2 §8)
    # ------------------------------------------------------------------
    #
    # When the Drive backend can't persist a turn (network flake, quota
    # exhaustion, transient 5xx), the GoogleDriveMemoryStore falls back
    # to writing the *incremental* messages here with ``pending_sync=1``.
    # The :class:`_PendingSyncWorker` daemon polls
    # :meth:`list_pending_session_ids`, replays the pending messages to
    # Drive via :meth:`pop_pending`, and only commits the dequeue once
    # the Drive write succeeds — so a worker crash mid-sync leaves the
    # rows in place for the next attempt.

    def save_pending(self, session_id: str, messages: list[Message]) -> None:
        """Append messages with ``pending_sync=1`` so the worker picks them up.

        Same wire format as :meth:`save`; only the flag column differs.
        Empty input is a no-op.
        """
        if not messages:
            return
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            for msg in messages:
                tool_calls_json = json.dumps(msg.tool_calls) if msg.tool_calls else None
                conn.execute(
                    "INSERT INTO messages "
                    "(session_id, role, content, name, tool_call_id, tool_calls, "
                    "timestamp, metadata, pending_sync) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
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

    def pop_pending(self, session_id: str) -> list[Message]:
        """Return + delete pending rows for a session, atomically.

        Used by :class:`_PendingSyncWorker` after a successful Drive
        replay. The fetch and delete share a single ``BEGIN IMMEDIATE``
        transaction — SQLite acquires a reserved write lock at BEGIN,
        so two concurrent ``pop_pending`` calls (e.g. the daemon
        thread + a manual flush) serialize cleanly: one wins the lock
        and pops the rows, the other waits, then sees no pending rows
        and returns an empty list. A crash between SELECT and DELETE
        rolls back, leaving the rows for the next attempt.
        """
        conn = self._connect()
        # ``isolation_level=None`` puts ``conn`` in autocommit mode so
        # the explicit ``BEGIN IMMEDIATE`` is the sole transaction
        # boundary. Without this, sqlite3's implicit transaction
        # management runs first and ``BEGIN IMMEDIATE`` would error.
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id, role, content, name, tool_call_id, tool_calls "
                "FROM messages WHERE session_id = ? AND pending_sync = 1 "
                "ORDER BY id",
                (session_id,),
            ).fetchall()
            if not rows:
                conn.execute("COMMIT")
                return []
            messages = [
                Message(
                    role=MessageRole(row[1]),
                    content=row[2],
                    name=row[3],
                    tool_call_id=row[4],
                    tool_calls=json.loads(row[5]) if row[5] else None,
                )
                for row in rows
            ]
            ids = [row[0] for row in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", ids)
            conn.execute("COMMIT")
            return messages
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def list_pending_session_ids(self) -> list[str]:
        """Distinct session ids that currently have at least one pending row."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM messages "
                "WHERE pending_sync = 1 ORDER BY session_id"
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()


# Forward-looking alias that mirrors the naming convention used by the
# other storage layers (`LocalFileStore`, `LocalMarkdownScratchpad`,
# `SQLiteSessionStore`). Both names refer to the same class; new code
# should prefer ``LocalSQLiteMemoryStore`` for consistency, existing
# imports of ``SQLiteMemoryStore`` continue to work unchanged.
LocalSQLiteMemoryStore = SQLiteMemoryStore


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
        # Turn transaction state — see turn() below.
        self._in_turn: bool = False
        self._turn_buffer: list[Message] = []
        self._turn_add_count: int = 0
        # Load previous conversation
        self.messages = self.store.load(session_id)

    def add(self, role: MessageRole, content: str, **kwargs: Any) -> None:
        """Add message and persist to store.

        Inside a :meth:`turn` context, the store write is buffered and
        flushed atomically at turn-end; a process crash mid-turn leaves
        the store untouched. Outside a turn (legacy path), every add is
        autocommitted — same behaviour as pre-transaction code.
        """
        super().add(role, content, **kwargs)
        if self._in_turn:
            self._turn_buffer.append(self.messages[-1])
            self._turn_add_count += 1
        else:
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

    def truncate_to(self, length: int) -> None:
        """Truncate messages to ``length`` both in memory AND in the store.

        Overrides :meth:`AgentMemory.truncate_to` so a rollback after a
        failed agent turn also deletes the orphaned rows from the backing
        store — otherwise ``PersistentMemory.__init__`` would resurrect
        them on the next session load.

        Inside a :meth:`turn` context, the store has not been written to
        yet, so this only truncates the in-memory list and the pending
        buffer.
        """
        if length < 0:
            length = 0
        current_len = len(self.messages)
        if length >= current_len:
            return
        delta = current_len - length

        if self._in_turn:
            # Buffered writes haven't touched the store; sync in-memory
            # and the pending buffer only.
            super().truncate_to(length)
            drop = min(delta, len(self._turn_buffer))
            if drop:
                del self._turn_buffer[-drop:]
            self._turn_add_count = max(0, self._turn_add_count - delta)
            return

        # Truncate in-memory first so callers see a consistent view even
        # if the store call raises.
        super().truncate_to(length)
        try:
            self.store.delete_tail(self.session_id, delta)
        except Exception as e:
            logger.warning(
                "Failed to delete %d tail messages from store for session %s: %s",
                delta,
                self.session_id,
                e,
            )
            raise

    @contextmanager
    def turn(self) -> Iterator[None]:
        """Buffer writes during one agent turn; flush atomically on exit.

        Normal exit (``return``): buffered messages are saved to the
        store in a single ``save()`` call. Exception exit (including
        ``KeyboardInterrupt`` / ``SystemExit``): buffered messages are
        discarded and the in-memory list is truncated back to its
        pre-turn length. The store is never touched mid-turn, so a
        process kill between ``add_assistant(tool_calls=...)`` and the
        subsequent ``add_tool_result`` calls cannot corrupt the session.

        Nested calls raise :class:`RuntimeError`. When
        ``OPENBENCH_TURN_TRANSACTION=0``, this is a no-op and the
        existing per-message autocommit path is used.
        """
        if not _turn_transaction_enabled():
            yield
            return

        if self._in_turn:
            raise RuntimeError("Nested PersistentMemory.turn() is not supported")

        self._in_turn = True
        self._turn_buffer = []
        self._turn_add_count = 0
        success = False
        try:
            yield
            success = True
        finally:
            # Clear flag BEFORE the store call so a failure there doesn't
            # strand the object in a half-in-turn state.
            self._in_turn = False
            buffer = self._turn_buffer
            add_count = self._turn_add_count
            self._turn_buffer = []
            self._turn_add_count = 0

            if success:
                if buffer:
                    self.store.save(self.session_id, buffer)
            elif add_count > 0:
                # Remove turn-added messages from the in-memory tail.
                # _trim_oldest() during the turn removes from the front,
                # so the last add_count entries are still our adds.
                remove = min(add_count, len(self.messages))
                if remove:
                    del self.messages[-remove:]
