"""Append-only audit trail for compliance.

Mirrors the admin-store dual-backend pattern: a JSONL file for local
deployments (a JSON array would rewrite the whole file per event; JSONL
is genuinely append-only, which is the compliance point) and a Postgres
table for deployed environments.

Audit rows are deliberately excluded from the privacy retention sweep —
compliance logs outliving chat data is the point of having them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuditRecord:
    """One audit event. ``detail`` holds summaries, never full bodies."""

    action: str
    actor: str = ""
    role: str = ""
    target: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    ts: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "actor": self.actor,
            "role": self.role,
            "action": self.action,
            "target": self.target,
            "detail": dict(self.detail),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditRecord":
        detail = data.get("detail")
        return cls(
            action=str(data.get("action", "")),
            actor=str(data.get("actor", "")),
            role=str(data.get("role", "")),
            target=str(data.get("target", "")),
            detail=dict(detail) if isinstance(detail, dict) else {},
            status=str(data.get("status", "ok")),
            ts=str(data.get("ts", "")),
        )


def _matches(
    record: AuditRecord,
    *,
    actor: str | None,
    action: str | None,
    since: str | None,
    until: str | None,
) -> bool:
    if actor and record.actor != actor:
        return False
    if action and not record.action.startswith(action):
        return False
    # ISO-8601 timestamps compare lexicographically.
    if since and record.ts < since:
        return False
    if until and record.ts > until:
        return False
    return True


class JsonAuditStore:
    """JSONL-backed audit log at ``<root>/admin/audit_log.jsonl``."""

    def __init__(self, root: str | Path):
        self.path = Path(root).expanduser().resolve() / "admin" / "audit_log.jsonl"

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _read_all(self) -> list[AuditRecord]:
        if not self.path.exists():
            return []
        records: list[AuditRecord] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(AuditRecord.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Skipping malformed audit line in %s", self.path)
        except OSError:
            logger.warning("Could not read audit log %s", self.path)
        return records

    def list(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditRecord]:
        """Newest-first filtered slice."""
        matched = [
            record
            for record in self._read_all()
            if _matches(record, actor=actor, action=action, since=since, until=until)
        ]
        matched.sort(key=lambda record: record.ts, reverse=True)
        return matched[offset : offset + limit]

    def count(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> int:
        return sum(
            1
            for record in self._read_all()
            if _matches(record, actor=actor, action=action, since=since, until=until)
        )


class PostgresAuditStore:
    """PostgreSQL-backed audit log for deployed environments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_audit_log",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def append(self, record: AuditRecord) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (ts, actor, role, action, target, detail, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.ts,
                        record.actor,
                        record.role,
                        record.action,
                        record.target,
                        json.dumps(record.detail, ensure_ascii=False),
                        record.status,
                    ),
                )
            conn.commit()

    def _where(
        self,
        *,
        actor: str | None,
        action: str | None,
        since: str | None,
        until: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if actor:
            clauses.append("actor = %s")
            params.append(actor)
        if action:
            clauses.append("action LIKE %s")
            params.append(action + "%")
        if since:
            clauses.append("ts >= %s")
            params.append(since)
        if until:
            clauses.append("ts <= %s")
            params.append(until)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def list(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditRecord]:
        where, params = self._where(actor=actor, action=action, since=since, until=until)
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ts, actor, role, action, target, detail, status
                FROM {self.table_name}{where}
                ORDER BY ts DESC, id DESC LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cur.fetchall()
        return [self._record_from_row(row) for row in rows]

    def count(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> int:
        where, params = self._where(actor=actor, action=action, since=since, until=until)
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self.table_name}{where}", params)
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id BIGSERIAL PRIMARY KEY,
                        ts TEXT NOT NULL,
                        actor TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT '',
                        action TEXT NOT NULL,
                        target TEXT NOT NULL DEFAULT '',
                        detail JSONB NOT NULL DEFAULT '{{}}',
                        status TEXT NOT NULL DEFAULT 'ok'
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self.table_name}_ts "
                    f"ON {self.table_name} (ts DESC)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self.table_name}_actor "
                    f"ON {self.table_name} (actor)"
                )
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresAuditStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _record_from_row(row: Any) -> AuditRecord:
        detail = row[5]
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = {}
        return AuditRecord(
            ts=str(row[0]),
            actor=str(row[1] or ""),
            role=str(row[2] or ""),
            action=str(row[3] or ""),
            target=str(row[4] or ""),
            detail=detail if isinstance(detail, dict) else {},
            status=str(row[6] or "ok"),
        )


class _ExternalConnection:
    """Context manager that never closes a borrowed connection."""

    def __init__(self, conn: Any):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


def build_audit_store(root: str | Path):
    """Postgres when ``GENERAL_CHAT_DATABASE_URL`` is set, JSONL otherwise."""
    import os

    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL", "").strip()
    if database_url:
        return PostgresAuditStore(database_url)
    return JsonAuditStore(root)
