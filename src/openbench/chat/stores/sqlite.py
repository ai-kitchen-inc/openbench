"""SQLite-backed SessionStore.

Stores each session as a single JSON blob keyed by session_id. Schema
is intentionally simple — no per-message normalization — because the
UI never queries individual messages; it loads the full session or
lists summaries.

If we later need per-message queries (e.g. full-text search across
turns), normalize to a separate ``messages`` table mirroring
``SQLiteMemoryStore``.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from openbench.chat.session import ChatSession, MessageRole
from openbench.chat.session_store import SessionOwnershipError, SessionStore, SessionSummary

if TYPE_CHECKING:
    from pathlib import Path


class SQLiteSessionStore(SessionStore):
    """Store ChatSessions as JSON blobs in a local SQLite database.

    Thread-safe via SQLite's built-in locking. Each call opens a short
    connection; no pooling.

    Example:
        >>> store = SQLiteSessionStore(".openbench/sessions.db")
        >>> store.save(session)
        >>> store.list(limit=10)
    """

    def __init__(self, db_path: str | Path = ".openbench/sessions.db", owner: str | None = None):
        """Initialize the store, creating the database file if needed.

        Args:
            db_path: Path to the SQLite file. Parent directories are
                created automatically.
            owner: Optional owner scope. ``None`` keeps single-tenant
                behavior; a string scopes every operation to that
                owner's sessions (see ``SessionStore`` docstring).
        """
        self.db_path = str(db_path)
        self.owner = owner
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the sessions table and index if not present."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    preview TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT ''
                )
                """)
            # Migrate pre-owner databases; a duplicate-column error means the
            # column already exists (fresh table above, or migrated earlier).
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE sessions ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated "
                "ON sessions(owner, updated_at DESC)"
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection."""
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _compute_preview(session: ChatSession, max_chars: int = 120) -> str:
        """First user message, truncated for sidebar display."""
        for msg in session.messages:
            if msg.role == MessageRole.USER and msg.content:
                text = msg.content.strip().replace("\n", " ")
                if len(text) > max_chars:
                    return text[: max_chars - 1] + "\u2026"
                return text
        return ""

    def save(self, session: ChatSession) -> None:
        """Persist a session (overwrites any existing row with same id).

        Owner-scoped stores claim the id on first save and raise
        :class:`SessionOwnershipError` if the id belongs to another
        owner; the existing row is left untouched.
        """
        data_json = json.dumps(session.to_dict(), ensure_ascii=False)
        preview = self._compute_preview(session)
        conn = self._connect()
        try:
            if self.owner is None:
                # Legacy single-tenant upsert. Never touches the owner
                # column so an unscoped save cannot strip ownership.
                conn.execute(
                    """
                    INSERT INTO sessions
                        (session_id, title, created_at, updated_at,
                         message_count, preview, data, owner)
                    VALUES (?, ?, ?, ?, ?, ?, ?, '')
                    ON CONFLICT(session_id) DO UPDATE SET
                        title = excluded.title,
                        updated_at = excluded.updated_at,
                        message_count = excluded.message_count,
                        preview = excluded.preview,
                        data = excluded.data
                    """,
                    (
                        session.session_id,
                        session.title,
                        session.created_at.isoformat(),
                        session.updated_at.isoformat(),
                        len(session.messages),
                        preview,
                        data_json,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO sessions
                        (session_id, title, created_at, updated_at,
                         message_count, preview, data, owner)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        title = excluded.title,
                        updated_at = excluded.updated_at,
                        message_count = excluded.message_count,
                        preview = excluded.preview,
                        data = excluded.data
                    WHERE sessions.owner = excluded.owner
                    """,
                    (
                        session.session_id,
                        session.title,
                        session.created_at.isoformat(),
                        session.updated_at.isoformat(),
                        len(session.messages),
                        preview,
                        data_json,
                        self.owner,
                    ),
                )
                if cursor.rowcount == 0:
                    raise SessionOwnershipError(session.session_id)
            conn.commit()
        finally:
            conn.close()

    def load(self, session_id: str) -> ChatSession | None:
        """Load a full session by id; returns None if absent."""
        query = "SELECT data FROM sessions WHERE session_id = ?"
        params: tuple = (session_id,)
        if self.owner is not None:
            query += " AND owner = ?"
            params = (session_id, self.owner)
        conn = self._connect()
        try:
            row = conn.execute(query, params).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return ChatSession.from_dict(json.loads(row[0]))

    def list(self, limit: int = 50, offset: int = 0) -> list[SessionSummary]:
        """List session summaries, newest updated first."""
        where = ""
        params: tuple = (limit, offset)
        if self.owner is not None:
            where = "WHERE owner = ?"
            params = (self.owner, limit, offset)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT session_id, title, created_at, updated_at,
                       message_count, preview
                FROM sessions
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
        return [
            SessionSummary(
                session_id=row[0],
                title=row[1],
                created_at=datetime.fromisoformat(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                message_count=row[4],
                preview=row[5],
            )
            for row in rows
        ]

    def delete(self, session_id: str) -> None:
        """Delete a session; no-op if session_id is unknown."""
        query = "DELETE FROM sessions WHERE session_id = ?"
        params: tuple = (session_id,)
        if self.owner is not None:
            query += " AND owner = ?"
            params = (session_id, self.owner)
        conn = self._connect()
        try:
            conn.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    def search(self, query: str, limit: int = 20) -> list[SessionSummary]:
        """Keyword LIKE search over title + preview + data.

        Cheap fallback when no FTS index is configured. Backends that
        want real full-text search should layer SQLite FTS5 on top.
        """
        pattern = f"%{query}%"
        owner_clause = ""
        params: tuple = (pattern, pattern, pattern, limit)
        if self.owner is not None:
            owner_clause = "AND owner = ?"
            params = (pattern, pattern, pattern, self.owner, limit)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT session_id, title, created_at, updated_at,
                       message_count, preview
                FROM sessions
                WHERE (title LIKE ? OR preview LIKE ? OR data LIKE ?)
                {owner_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
        return [
            SessionSummary(
                session_id=row[0],
                title=row[1],
                created_at=datetime.fromisoformat(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                message_count=row[4],
                preview=row[5],
            )
            for row in rows
        ]
