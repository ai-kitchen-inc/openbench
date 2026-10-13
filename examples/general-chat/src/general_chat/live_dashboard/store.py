"""Persistence for live dashboards (JSON files locally, Postgres when deployed).

Same shape as ``general_chat.agent_store``: the whole record lives as JSON in
``config``; ``owner``, ``enabled``, ``is_public`` and ``next_run_at`` are real
columns so the scheduler and the public routes can filter without decoding
every row.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from general_chat.live_dashboard.models import ID_RE, LiveDashboardRecord, utc_now_iso

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        # Windows refuses to replace a file another thread still has open for
        # reading; a short retry covers the scheduler/route read overlap.
        for attempt in range(5):
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _is_due(record: LiveDashboardRecord, now_iso: str) -> bool:
    if not record.enabled or record.refresh_interval_seconds <= 0:
        return False
    return record.next_run_at is None or record.next_run_at <= now_iso


class JsonLiveDashboardStore:
    """One JSON file per dashboard under ``<root>/live_dashboards/``."""

    def __init__(self, root: str | Path):
        self._dir = Path(root).expanduser().resolve() / "live_dashboards"
        self._lock = threading.Lock()

    def list(self, owner: str | None = None) -> list[LiveDashboardRecord]:
        records = [record for record in self._read_all() if owner is None or record.owner == owner]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def get(self, dashboard_id: str) -> LiveDashboardRecord | None:
        path = self._path_for(dashboard_id)
        if path is None or not path.exists():
            return None
        with self._lock:
            return self._read_one(path)

    def save(self, record: LiveDashboardRecord) -> None:
        path = self._path_for(record.id)
        if path is None:
            raise ValueError(f"invalid dashboard id: {record.id!r}")
        record.updated_at = utc_now_iso()
        with self._lock:
            _atomic_write_json(path, record.to_dict())

    def delete(self, dashboard_id: str) -> bool:
        path = self._path_for(dashboard_id)
        if path is None or not path.exists():
            return False
        with self._lock:
            path.unlink()
        return True

    def list_due(self, now_iso: str | None = None) -> list[LiveDashboardRecord]:
        moment = now_iso or utc_now_iso()
        return [record for record in self._read_all() if _is_due(record, moment)]

    def _path_for(self, dashboard_id: str) -> Path | None:
        if not isinstance(dashboard_id, str) or not ID_RE.match(dashboard_id):
            return None
        return self._dir / f"{dashboard_id}.json"

    def _read_all(self) -> list[LiveDashboardRecord]:
        if not self._dir.is_dir():
            return []
        records: list[LiveDashboardRecord] = []
        with self._lock:
            for path in sorted(self._dir.glob("*.json")):
                record = self._read_one(path)
                if record is not None:
                    records.append(record)
        return records

    def _read_one(self, path: Path) -> LiveDashboardRecord | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            record = LiveDashboardRecord.from_dict(data)
        except Exception:  # one corrupt file must not take the scheduler down
            logger.warning("Failed to load live dashboard file %s", path, exc_info=True)
            return None
        return record if record.id else None


class PostgresLiveDashboardStore:
    """PostgreSQL-backed store for deployed environments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_live_dashboards",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def list(self, owner: str | None = None) -> list[LiveDashboardRecord]:
        with self._connection() as conn, conn.cursor() as cur:
            if owner is None:
                cur.execute(f"SELECT config FROM {self.table_name} ORDER BY created_at DESC")
            else:
                cur.execute(
                    f"SELECT config FROM {self.table_name} WHERE owner = %s ORDER BY created_at DESC",
                    (owner,),
                )
            rows = cur.fetchall()
        return [record for record in map(self._record_from_row, rows) if record is not None]

    def get(self, dashboard_id: str) -> LiveDashboardRecord | None:
        if not isinstance(dashboard_id, str) or not ID_RE.match(dashboard_id):
            return None
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT config FROM {self.table_name} WHERE id = %s", (dashboard_id,))
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def save(self, record: LiveDashboardRecord) -> None:
        if not ID_RE.match(record.id):
            raise ValueError(f"invalid dashboard id: {record.id!r}")
        record.updated_at = utc_now_iso()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (id, owner, enabled, is_public, next_run_at, created_at, config)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        owner = EXCLUDED.owner,
                        enabled = EXCLUDED.enabled,
                        is_public = EXCLUDED.is_public,
                        next_run_at = EXCLUDED.next_run_at,
                        config = EXCLUDED.config
                    """,
                    (
                        record.id,
                        record.owner,
                        record.enabled,
                        record.public,
                        record.next_run_at,
                        record.created_at,
                        json.dumps(record.to_dict(), ensure_ascii=False, default=str),
                    ),
                )
            conn.commit()

    def delete(self, dashboard_id: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name} WHERE id = %s", (dashboard_id,))
                rowcount = cur.rowcount
            conn.commit()
        return bool(rowcount)

    def list_due(self, now_iso: str | None = None) -> list[LiveDashboardRecord]:
        moment = now_iso or utc_now_iso()
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT config FROM {self.table_name} "
                "WHERE enabled = TRUE AND (next_run_at IS NULL OR next_run_at <= %s)",
                (moment,),
            )
            rows = cur.fetchall()
        records = [record for record in map(self._record_from_row, rows) if record is not None]
        # The interval lives inside config, so finish the filter in Python.
        return [record for record in records if _is_due(record, moment)]

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        is_public BOOLEAN NOT NULL DEFAULT FALSE,
                        next_run_at TEXT,
                        created_at TEXT NOT NULL,
                        config TEXT NOT NULL
                    )
                    """)
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self.table_name}_owner_idx "
                    f"ON {self.table_name} (owner)"
                )
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresLiveDashboardStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _record_from_row(row: Any) -> LiveDashboardRecord | None:
        raw = row[0]
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            record = LiveDashboardRecord.from_dict(data)
        except Exception:
            logger.warning("Malformed live dashboard config row; skipping", exc_info=True)
            return None
        return record if record.id else None


class _ExternalConnection:
    """Context manager that never closes a borrowed connection."""

    def __init__(self, conn: Any):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


def build_live_dashboard_store(root: str | Path):
    """Postgres when ``GENERAL_CHAT_DATABASE_URL`` is set, JSON otherwise."""
    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL", "").strip()
    if database_url:
        return PostgresLiveDashboardStore(database_url)
    return JsonLiveDashboardStore(root)
