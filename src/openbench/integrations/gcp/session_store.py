"""PostgreSQL-backed ``SessionStore`` for Cloud SQL deployments."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from openbench.chat.session import ChatSession, MessageRole
from openbench.chat.session_store import SessionStore, SessionSummary

__all__ = ["PostgresSessionStore"]


def _missing_dep_message() -> str:
    return (
        "PostgresSessionStore requires the 'gcp' extras. Install with:\n"
        "    pip install openbench[gcp]\n"
        "which pulls psycopg."
    )


class PostgresSessionStore(SessionStore):
    """Store ``ChatSession`` JSON blobs in PostgreSQL / Cloud SQL."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_sessions",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def save(self, session: ChatSession) -> None:
        preview = self._compute_preview(session)
        data = json.dumps(session.to_dict(), ensure_ascii=False)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (session_id, title, created_at, updated_at,
                         message_count, preview, data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(session_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at,
                        message_count = EXCLUDED.message_count,
                        preview = EXCLUDED.preview,
                        data = EXCLUDED.data
                    """,
                    (
                        session.session_id,
                        session.title,
                        session.created_at,
                        session.updated_at,
                        len(session.messages),
                        preview,
                        data,
                    ),
                )
            conn.commit()

    def load(self, session_id: str) -> ChatSession | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT data FROM {self.table_name} WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        data = row[0]
        if isinstance(data, str):
            data = json.loads(data)
        return ChatSession.from_dict(data)

    def list(self, limit: int = 50, offset: int = 0) -> list[SessionSummary]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT session_id, title, created_at, updated_at,
                       message_count, preview
                FROM {self.table_name}
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
        return [
            SessionSummary(
                session_id=row[0],
                title=row[1],
                created_at=_as_datetime(row[2]),
                updated_at=_as_datetime(row[3]),
                message_count=row[4],
                preview=row[5],
            )
            for row in rows
        ]

    def delete(self, session_id: str) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE session_id = %s",
                    (session_id,),
                )
            conn.commit()

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        session_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        preview TEXT NOT NULL DEFAULT '',
                        data JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_updated "
                    f"ON {self.table_name} (updated_at DESC)"
                )
            conn.commit()

    @staticmethod
    def _compute_preview(session: ChatSession, max_chars: int = 120) -> str:
        for msg in session.messages:
            if msg.role == MessageRole.USER and msg.content:
                text = msg.content.strip().replace("\n", " ")
                if len(text) > max_chars:
                    return text[: max_chars - 1] + "\u2026"
                return text
        return ""

    def _connection(self) -> Any:
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(_missing_dep_message()) from exc
        return psycopg.connect(self.database_url)


class _ExternalConnection:
    def __init__(self, conn: Any):
        self.conn = conn

    def __enter__(self) -> Any:
        return self.conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
