"""Per-call LLM usage rows for metering and cost dashboards.

Dual backend like the other stores: JSONL for local deployments (rows
are append-only facts, same rationale as the audit log) and a Postgres
table for deployed environments.

Row shape::

    {ts, owner, session_id, model, prompt_tokens, completion_tokens,
     total_tokens, cost_usd}

``month`` filters take ``"YYYY-MM"`` and compare against the ISO ``ts``
prefix, which works identically on both backends.
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


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@dataclass
class UsageRecord:
    owner: str
    session_id: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    ts: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "owner": self.owner,
            "sessionId": self.session_id,
            "model": self.model,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "costUsd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsageRecord":
        return cls(
            owner=str(data.get("owner", "")),
            session_id=str(data.get("sessionId", data.get("session_id", ""))),
            model=str(data.get("model", "")),
            prompt_tokens=int(data.get("promptTokens", data.get("prompt_tokens", 0)) or 0),
            completion_tokens=int(
                data.get("completionTokens", data.get("completion_tokens", 0)) or 0
            ),
            total_tokens=int(data.get("totalTokens", data.get("total_tokens", 0)) or 0),
            cost_usd=float(data.get("costUsd", data.get("cost_usd", 0.0)) or 0.0),
            ts=str(data.get("ts", "")),
        )


def _empty_summary() -> dict[str, Any]:
    return {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "costUsd": 0.0,
        "calls": 0,
    }


def _add_to_summary(summary: dict[str, Any], record: UsageRecord) -> None:
    summary["promptTokens"] += record.prompt_tokens
    summary["completionTokens"] += record.completion_tokens
    summary["totalTokens"] += record.total_tokens
    summary["costUsd"] += record.cost_usd
    summary["calls"] += 1


class JsonUsageStore:
    """JSONL-backed usage log at ``<root>/admin/usage.jsonl``."""

    def __init__(self, root: str | Path):
        self.path = Path(root).expanduser().resolve() / "admin" / "usage.jsonl"

    def append(self, record: UsageRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _read_all(self) -> list[UsageRecord]:
        if not self.path.exists():
            return []
        records: list[UsageRecord] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(UsageRecord.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        logger.warning("Skipping malformed usage line in %s", self.path)
        except OSError:
            logger.warning("Could not read usage log %s", self.path)
        return records

    def summarize_owner(self, owner: str, month: str) -> dict[str, Any]:
        summary = _empty_summary()
        for record in self._read_all():
            if record.owner == owner and record.ts.startswith(month):
                _add_to_summary(summary, record)
        return summary

    def summarize_all(self, month: str) -> list[dict[str, Any]]:
        by_owner: dict[str, dict[str, Any]] = {}
        for record in self._read_all():
            if not record.ts.startswith(month):
                continue
            summary = by_owner.setdefault(record.owner, _empty_summary())
            _add_to_summary(summary, record)
        return [
            {"owner": owner, **summary}
            for owner, summary in sorted(by_owner.items())
        ]

    def recent(self, owner: str, limit: int = 20) -> list[UsageRecord]:
        rows = [record for record in self._read_all() if record.owner == owner]
        rows.sort(key=lambda record: record.ts, reverse=True)
        return rows[:limit]


class PostgresUsageStore:
    """PostgreSQL-backed usage log for deployed environments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_usage",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def append(self, record: UsageRecord) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (ts, owner, session_id, model, prompt_tokens,
                         completion_tokens, total_tokens, cost_usd)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.ts,
                        record.owner,
                        record.session_id,
                        record.model,
                        record.prompt_tokens,
                        record.completion_tokens,
                        record.total_tokens,
                        record.cost_usd,
                    ),
                )
            conn.commit()

    def summarize_owner(self, owner: str, month: str) -> dict[str, Any]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COALESCE(SUM(prompt_tokens), 0),
                       COALESCE(SUM(completion_tokens), 0),
                       COALESCE(SUM(total_tokens), 0),
                       COALESCE(SUM(cost_usd), 0),
                       COUNT(*)
                FROM {self.table_name}
                WHERE owner = %s AND ts LIKE %s
                """,
                (owner, month + "%"),
            )
            row = cur.fetchone()
        return {
            "promptTokens": int(row[0]),
            "completionTokens": int(row[1]),
            "totalTokens": int(row[2]),
            "costUsd": float(row[3]),
            "calls": int(row[4]),
        }

    def summarize_all(self, month: str) -> list[dict[str, Any]]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT owner,
                       COALESCE(SUM(prompt_tokens), 0),
                       COALESCE(SUM(completion_tokens), 0),
                       COALESCE(SUM(total_tokens), 0),
                       COALESCE(SUM(cost_usd), 0),
                       COUNT(*)
                FROM {self.table_name}
                WHERE ts LIKE %s
                GROUP BY owner ORDER BY owner
                """,
                (month + "%",),
            )
            rows = cur.fetchall()
        return [
            {
                "owner": str(row[0]),
                "promptTokens": int(row[1]),
                "completionTokens": int(row[2]),
                "totalTokens": int(row[3]),
                "costUsd": float(row[4]),
                "calls": int(row[5]),
            }
            for row in rows
        ]

    def recent(self, owner: str, limit: int = 20) -> list[UsageRecord]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ts, owner, session_id, model, prompt_tokens,
                       completion_tokens, total_tokens, cost_usd
                FROM {self.table_name}
                WHERE owner = %s ORDER BY ts DESC, id DESC LIMIT %s
                """,
                (owner, limit),
            )
            rows = cur.fetchall()
        return [
            UsageRecord(
                ts=str(row[0]),
                owner=str(row[1]),
                session_id=str(row[2] or ""),
                model=str(row[3] or ""),
                prompt_tokens=int(row[4] or 0),
                completion_tokens=int(row[5] or 0),
                total_tokens=int(row[6] or 0),
                cost_usd=float(row[7] or 0.0),
            )
            for row in rows
        ]

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id BIGSERIAL PRIMARY KEY,
                        ts TEXT NOT NULL,
                        owner TEXT NOT NULL,
                        session_id TEXT NOT NULL DEFAULT '',
                        model TEXT NOT NULL DEFAULT '',
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self.table_name}_owner_ts "
                    f"ON {self.table_name} (owner, ts DESC)"
                )
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresUsageStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)


class _ExternalConnection:
    """Context manager that never closes a borrowed connection."""

    def __init__(self, conn: Any):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


def build_usage_store(root: str | Path):
    """Postgres when ``GENERAL_CHAT_DATABASE_URL`` is set, JSONL otherwise."""
    import os

    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL", "").strip()
    if database_url:
        return PostgresUsageStore(database_url)
    return JsonUsageStore(root)
