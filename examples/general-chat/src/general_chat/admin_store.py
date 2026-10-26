"""User accounts and app settings stores.

Dual backend, mirroring :mod:`general_chat.sources`:

- JSON files under ``<storage_root>/admin/`` for local development.
- PostgreSQL tables (``openbench_users``, ``openbench_app_settings``)
  when ``GENERAL_CHAT_DATABASE_URL`` is set.

Users carry a role (``admin`` or ``user``) that the auth middleware
resolves after Firebase token verification. Settings is a small
key/value JSON store used for admin-managed app state (capability
flags, persona overrides).
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

ROLES = ("admin", "user")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DuplicateUserError(ValueError):
    """Raised when adding a user whose email already exists."""


class UnknownUserError(KeyError):
    """Raised when updating a user that does not exist."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not _EMAIL_RE.match(normalized):
        raise ValueError(f"Invalid email address: {email!r}")
    return normalized


def validate_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value not in ROLES:
        raise ValueError(f"Invalid role {role!r}; expected one of {ROLES}")
    return value


@dataclass
class UserRecord:
    """A single account granted access to the app.

    ``group`` is the workspace/team axis, orthogonal to ``role``; empty
    means no group. The Postgres column is ``group_name`` (``group`` is
    an SQL keyword) but the JSON/dict key stays ``group``.
    """

    email: str
    role: str = "user"
    display_name: str = ""
    created_at: str = field(default_factory=_utcnow_iso)
    added_by: str = ""
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "role": self.role,
            "displayName": self.display_name,
            "createdAt": self.created_at,
            "addedBy": self.added_by,
            "group": self.group,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserRecord:
        return cls(
            email=normalize_email(str(data.get("email", ""))),
            role=str(data.get("role", "user")),
            display_name=str(data.get("displayName", data.get("display_name", "")) or ""),
            created_at=str(data.get("createdAt", data.get("created_at", "")) or _utcnow_iso()),
            added_by=str(data.get("addedBy", data.get("added_by", "")) or ""),
            group=str(data.get("group", data.get("group_name", "")) or ""),
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


class JsonUserStore:
    """JSON-file-backed user store for local development."""

    def __init__(self, root: str | Path):
        self._path = Path(root).expanduser().resolve() / "admin" / "users.json"

    def list_users(self) -> list[UserRecord]:
        return sorted(self._read().values(), key=lambda record: record.email)

    def get(self, email: str) -> UserRecord | None:
        return self._read().get(normalize_email(email))

    def add(
        self,
        email: str,
        role: str = "user",
        *,
        display_name: str = "",
        added_by: str = "",
    ) -> UserRecord:
        email = validate_email(email)
        role = validate_role(role)
        users = self._read()
        if email in users:
            raise DuplicateUserError(f"User already exists: {email}")
        record = UserRecord(
            email=email,
            role=role,
            display_name=display_name.strip(),
            added_by=added_by,
        )
        users[email] = record
        self._write(users)
        return record

    def update(
        self,
        email: str,
        *,
        role: str | None = None,
        display_name: str | None = None,
        group: str | None = None,
    ) -> UserRecord:
        email = normalize_email(email)
        users = self._read()
        record = users.get(email)
        if record is None:
            raise UnknownUserError(email)
        if role is not None:
            record.role = validate_role(role)
        if display_name is not None:
            record.display_name = display_name.strip()
        if group is not None:
            record.group = group.strip()
        self._write(users)
        return record

    def remove(self, email: str) -> bool:
        email = normalize_email(email)
        users = self._read()
        if email not in users:
            return False
        del users[email]
        self._write(users)
        return True

    def count_admins(self) -> int:
        return sum(1 for record in self._read().values() if record.role == "admin")

    def _read(self) -> dict[str, UserRecord]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load user store file %s", self._path)
            return {}
        users: dict[str, UserRecord] = {}
        for item in data.get("users", []):
            record = UserRecord.from_dict(item)
            if record.email:
                users[record.email] = record
        return users

    def _write(self, users: dict[str, UserRecord]) -> None:
        payload = {"users": [record.to_dict() for record in sorted(users.values(), key=lambda r: r.email)]}
        _atomic_write_json(self._path, payload)


class PostgresUserStore:
    """PostgreSQL-backed user store for deployed environments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_users",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def list_users(self) -> list[UserRecord]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT email, role, display_name, created_at, added_by, group_name
                FROM {self.table_name} ORDER BY email
                """
            )
            rows = cur.fetchall()
        return [self._record_from_row(row) for row in rows]

    def get(self, email: str) -> UserRecord | None:
        email = normalize_email(email)
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT email, role, display_name, created_at, added_by, group_name
                FROM {self.table_name} WHERE email = %s
                """,
                (email,),
            )
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

    def add(
        self,
        email: str,
        role: str = "user",
        *,
        display_name: str = "",
        added_by: str = "",
    ) -> UserRecord:
        email = validate_email(email)
        role = validate_role(role)
        record = UserRecord(
            email=email,
            role=role,
            display_name=display_name.strip(),
            added_by=added_by,
        )
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (email, role, display_name, created_at, added_by, group_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (
                        record.email,
                        record.role,
                        record.display_name,
                        record.created_at,
                        record.added_by,
                        record.group,
                    ),
                )
                inserted = cur.rowcount
            conn.commit()
        if not inserted:
            raise DuplicateUserError(f"User already exists: {email}")
        return record

    def update(
        self,
        email: str,
        *,
        role: str | None = None,
        display_name: str | None = None,
        group: str | None = None,
    ) -> UserRecord:
        email = normalize_email(email)
        assignments: list[str] = []
        params: list[Any] = []
        if role is not None:
            assignments.append("role = %s")
            params.append(validate_role(role))
        if display_name is not None:
            assignments.append("display_name = %s")
            params.append(display_name.strip())
        if group is not None:
            assignments.append("group_name = %s")
            params.append(group.strip())
        if assignments:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {self.table_name} SET {', '.join(assignments)} WHERE email = %s",
                        (*params, email),
                    )
                    updated = cur.rowcount
                conn.commit()
            if not updated:
                raise UnknownUserError(email)
        record = self.get(email)
        if record is None:
            raise UnknownUserError(email)
        return record

    def remove(self, email: str) -> bool:
        email = normalize_email(email)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name} WHERE email = %s", (email,))
                rowcount = cur.rowcount
            conn.commit()
        return bool(rowcount)

    def count_admins(self) -> int:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self.table_name} WHERE role = 'admin'")
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        email TEXT PRIMARY KEY,
                        role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                        display_name TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        added_by TEXT NOT NULL DEFAULT '',
                        group_name TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                # Additive migration for tables created before groups existed.
                cur.execute(
                    f"ALTER TABLE {self.table_name} "
                    "ADD COLUMN IF NOT EXISTS group_name TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresUserStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _record_from_row(row: Any) -> UserRecord:
        return UserRecord(
            email=str(row[0]),
            role=str(row[1]),
            display_name=str(row[2] or ""),
            created_at=str(row[3] or ""),
            added_by=str(row[4] or ""),
            group=str(row[5] or "") if len(row) > 5 else "",
        )


class JsonSettingsStore:
    """JSON-file-backed key/value settings store for local development."""

    def __init__(self, root: str | Path):
        self._path = Path(root).expanduser().resolve() / "admin" / "settings.json"

    def get(self, key: str) -> Any | None:
        entry = self._read().get(key)
        return entry.get("value") if isinstance(entry, dict) else None

    def set(self, key: str, value: Any, *, updated_by: str = "") -> None:
        data = self._read()
        data[key] = {
            "value": value,
            "updatedAt": _utcnow_iso(),
            "updatedBy": updated_by,
        }
        _atomic_write_json(self._path, data)

    def delete(self, key: str) -> bool:
        data = self._read()
        if key not in data:
            return False
        del data[key]
        _atomic_write_json(self._path, data)
        return True

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load settings store file %s", self._path)
            return {}
        return data if isinstance(data, dict) else {}


class PostgresSettingsStore:
    """PostgreSQL-backed key/value settings store for deployed environments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_app_settings",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def get(self, key: str) -> Any | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT value FROM {self.table_name} WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return None
        value = row[0]
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def set(self, key: str, value: Any, *, updated_by: str = "") -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name} (key, value, updated_at, updated_by)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                    """,
                    (key, payload, _utcnow_iso(), updated_by),
                )
            conn.commit()

    def delete(self, key: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name} WHERE key = %s", (key,))
                rowcount = cur.rowcount
            conn.commit()
        return bool(rowcount)

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        updated_at TEXT NOT NULL,
                        updated_by TEXT NOT NULL DEFAULT ''
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
                "PostgresSettingsStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)


class _ExternalConnection:
    def __init__(self, conn: Any):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def build_user_store(root: str | Path):
    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL")
    if database_url:
        return PostgresUserStore(database_url)
    return JsonUserStore(root)


def build_settings_store(root: str | Path):
    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL")
    if database_url:
        return PostgresSettingsStore(database_url)
    return JsonSettingsStore(root)


def seed_users(user_store: Any) -> int:
    """Seed the user store from env on first boot. Returns seeded count.

    Only runs when the store is empty: ``GENERAL_CHAT_BOOTSTRAP_ADMIN``
    emails become admins, ``GENERAL_CHAT_ALLOWED_EMAILS`` (the legacy
    allowlist) become regular users. Idempotent — a non-empty store is
    left untouched.
    """
    if user_store.list_users():
        return 0
    seeded = 0
    admins = _split_emails(os.getenv("GENERAL_CHAT_BOOTSTRAP_ADMIN", ""))
    members = _split_emails(os.getenv("GENERAL_CHAT_ALLOWED_EMAILS", ""))
    for email in admins:
        try:
            user_store.add(email, "admin", added_by="bootstrap")
            seeded += 1
        except (DuplicateUserError, ValueError) as exc:
            logger.warning("Skipping bootstrap admin %s: %s", email, exc)
    for email in members:
        if email in admins:
            continue
        try:
            user_store.add(email, "user", added_by="bootstrap")
            seeded += 1
        except (DuplicateUserError, ValueError) as exc:
            logger.warning("Skipping bootstrap user %s: %s", email, exc)
    if seeded:
        logger.info("Seeded %d user(s) from environment", seeded)
    else:
        logger.warning(
            "User store is empty and no GENERAL_CHAT_BOOTSTRAP_ADMIN / "
            "GENERAL_CHAT_ALLOWED_EMAILS set — nobody can sign in."
        )
    return seeded


def _split_emails(raw: str) -> list[str]:
    return [normalize_email(part) for part in raw.split(",") if part.strip()]
