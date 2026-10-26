"""PostgreSQL-backed ``MemoryStore`` for Cloud SQL deployments."""

from __future__ import annotations

import json
from typing import Any

from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.memory import MemoryStore

__all__ = ["PostgresMemoryStore"]


def _missing_dep_message() -> str:
    return (
        "PostgresMemoryStore requires the 'gcp' extras. Install with:\n"
        "    pip install openbench[gcp]\n"
        "which pulls psycopg."
    )


class PostgresMemoryStore(MemoryStore):
    """Append-only agent memory stored in PostgreSQL / Cloud SQL."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_messages",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def save(self, session_id: str, messages: list[Message]) -> None:
        if not messages:
            return
        with self._connection() as conn:
            with conn.cursor() as cur:
                for msg in messages:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name}
                            (session_id, role, content, name, tool_call_id, tool_calls)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            session_id,
                            msg.role.value,
                            msg.content,
                            msg.name,
                            msg.tool_call_id,
                            json.dumps(msg.tool_calls) if msg.tool_calls else None,
                        ),
                    )
            conn.commit()

    def load(self, session_id: str) -> list[Message]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT role, content, name, tool_call_id, tool_calls
                FROM {self.table_name}
                WHERE session_id = %s
                ORDER BY id
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [_message_from_row(row) for row in rows]

    def search(self, query: str, limit: int = 5) -> list[Message]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT role, content, name, tool_call_id, tool_calls
                FROM {self.table_name}
                WHERE content ILIKE %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (f"%{query}%", limit),
            )
            rows = cur.fetchall()
        return [_message_from_row(row) for row in rows]

    def list_sessions(self) -> list[str]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT session_id FROM {self.table_name} ORDER BY session_id")
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def delete_session(self, session_id: str) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE session_id = %s",
                    (session_id,),
                )
            conn.commit()

    def delete_tail(self, session_id: str, count: int) -> None:
        if count <= 0:
            return
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    DELETE FROM {self.table_name}
                    WHERE id IN (
                        SELECT id FROM {self.table_name}
                        WHERE session_id = %s
                        ORDER BY id DESC
                        LIMIT %s
                    )
                    """,
                    (session_id, count),
                )
            conn.commit()

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        name TEXT,
                        tool_call_id TEXT,
                        tool_calls JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_session "
                    f"ON {self.table_name} (session_id, id)"
                )
            conn.commit()

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


def _message_from_row(row: Any) -> Message:
    tool_calls = row[4]
    if isinstance(tool_calls, str):
        tool_calls = json.loads(tool_calls)
    return Message(
        role=MessageRole(row[0]),
        content=row[1],
        name=row[2],
        tool_call_id=row[3],
        tool_calls=tool_calls,
    )
