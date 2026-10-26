"""Team/workspace groups.

Groups are orthogonal to roles: a group scopes shared sources and can
override capability flags for its members. Store pattern mirrors
``admin_store``: JSON file for local development, Postgres for deployed
environments. Cascade behavior on delete (clearing members, purging the
group's sources, stripping capability overrides) lives at the route
layer — the store stays dumb.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class DuplicateGroupError(ValueError):
    """Raised when adding a group whose id already exists."""


class UnknownGroupError(KeyError):
    """Raised when updating a group that does not exist."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_group_name(name: str) -> str:
    """Derive the group id from its display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:64]
    return slug


def validate_group_id(group_id: str) -> str:
    value = group_id.strip().lower()
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(
            f"Invalid group id {group_id!r}; expected 1-64 chars of [a-z0-9-]"
        )
    return value


@dataclass
class GroupRecord:
    id: str
    name: str
    description: str = ""
    created_at: str = field(default_factory=_utcnow_iso)
    created_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroupRecord":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "") or ""),
            created_at=str(data.get("createdAt", data.get("created_at", "")) or _utcnow_iso()),
            created_by=str(data.get("createdBy", data.get("created_by", "")) or ""),
        )


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class JsonGroupStore:
    """JSON-file-backed group store at ``<root>/admin/groups.json``."""

    def __init__(self, root: str | Path):
        self._path = Path(root).expanduser().resolve() / "admin" / "groups.json"

    def list(self) -> list[GroupRecord]:
        return sorted(self._read().values(), key=lambda record: record.id)

    def get(self, group_id: str) -> GroupRecord | None:
        return self._read().get(group_id.strip().lower())

    def add(self, name: str, *, description: str = "", created_by: str = "") -> GroupRecord:
        slug = validate_group_id(slugify_group_name(name))
        groups = self._read()
        if slug in groups:
            raise DuplicateGroupError(f"Group already exists: {slug}")
        record = GroupRecord(
            id=slug,
            name=name.strip(),
            description=description.strip(),
            created_by=created_by,
        )
        groups[slug] = record
        self._write(groups)
        return record

    def update(
        self,
        group_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> GroupRecord:
        group_id = validate_group_id(group_id)
        groups = self._read()
        record = groups.get(group_id)
        if record is None:
            raise UnknownGroupError(group_id)
        if name is not None and name.strip():
            record.name = name.strip()
        if description is not None:
            record.description = description.strip()
        self._write(groups)
        return record

    def remove(self, group_id: str) -> bool:
        group_id = group_id.strip().lower()
        groups = self._read()
        if group_id not in groups:
            return False
        del groups[group_id]
        self._write(groups)
        return True

    def _read(self) -> dict[str, GroupRecord]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load group store file %s", self._path)
            return {}
        groups: dict[str, GroupRecord] = {}
        for item in data.get("groups", []):
            record = GroupRecord.from_dict(item)
            if record.id:
                groups[record.id] = record
        return groups

    def _write(self, groups: dict[str, GroupRecord]) -> None:
        payload = {
            "groups": [record.to_dict() for record in sorted(groups.values(), key=lambda r: r.id)]
        }
        _atomic_write_json(self._path, payload)


class PostgresGroupStore:
    """PostgreSQL-backed group store for deployed environments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_groups",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def list(self) -> list[GroupRecord]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, name, description, created_at, created_by
                FROM {self.table_name} ORDER BY id
                """
            )
            rows = cur.fetchall()
        return [self._record_from_row(row) for row in rows]

    def get(self, group_id: str) -> GroupRecord | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, name, description, created_at, created_by
                FROM {self.table_name} WHERE id = %s
                """,
                (group_id.strip().lower(),),
            )
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def add(self, name: str, *, description: str = "", created_by: str = "") -> GroupRecord:
        slug = validate_group_id(slugify_group_name(name))
        record = GroupRecord(
            id=slug,
            name=name.strip(),
            description=description.strip(),
            created_by=created_by,
        )
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (id, name, description, created_at, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        record.id,
                        record.name,
                        record.description,
                        record.created_at,
                        record.created_by,
                    ),
                )
                inserted = cur.rowcount
            conn.commit()
        if not inserted:
            raise DuplicateGroupError(f"Group already exists: {slug}")
        return record

    def update(
        self,
        group_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> GroupRecord:
        group_id = validate_group_id(group_id)
        assignments: list[str] = []
        params: list[Any] = []
        if name is not None and name.strip():
            assignments.append("name = %s")
            params.append(name.strip())
        if description is not None:
            assignments.append("description = %s")
            params.append(description.strip())
        if assignments:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {self.table_name} SET {', '.join(assignments)} WHERE id = %s",
                        (*params, group_id),
                    )
                    updated = cur.rowcount
                conn.commit()
            if not updated:
                raise UnknownGroupError(group_id)
        record = self.get(group_id)
        if record is None:
            raise UnknownGroupError(group_id)
        return record

    def remove(self, group_id: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE id = %s",
                    (group_id.strip().lower(),),
                )
                rowcount = cur.rowcount
            conn.commit()
        return bool(rowcount)

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        created_by TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresGroupStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _record_from_row(row: Any) -> GroupRecord:
        return GroupRecord(
            id=str(row[0]),
            name=str(row[1]),
            description=str(row[2] or ""),
            created_at=str(row[3] or ""),
            created_by=str(row[4] or ""),
        )


class _ExternalConnection:
    """Context manager that never closes a borrowed connection."""

    def __init__(self, conn: Any):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


def build_group_store(root: str | Path):
    """Postgres when ``GENERAL_CHAT_DATABASE_URL`` is set, JSON otherwise."""
    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL", "").strip()
    if database_url:
        return PostgresGroupStore(database_url)
    return JsonGroupStore(root)
