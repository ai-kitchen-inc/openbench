"""Persistent user registry for Dashboard Chat.

Users live in ``dashboard-users.json`` under the storage root (same
pattern as the auth secret and the per-user dashboard specs). The
built-in ``admin`` and ``guest`` accounts are merged in at read time
with a ``null`` password hash — they keep authenticating through the
env-overridable passwords in :mod:`dashboard_chat.auth`, so a fresh
install never writes a users file until the admin adds someone.

This module must not import :mod:`dashboard_chat.auth`
(auth imports users), so it resolves the storage root itself.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROLE_ADMIN = "admin"
ROLE_GUEST = "guest"
VALID_ROLES = (ROLE_ADMIN, ROLE_GUEST)

BUILTIN_USERNAMES = ("admin", "guest")
_BUILTIN_ROLES = {"admin": ROLE_ADMIN, "guest": ROLE_GUEST}

_USERS_FILENAME = "dashboard-users.json"
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{1,32}$")
_MIN_PASSWORD_LENGTH = 6
_PBKDF2_ITERATIONS = 600_000
_HASH_SCHEME = "pbkdf2_sha256"


class DuplicateUserError(ValueError):
    """A user with that username already exists."""


class BuiltinUserError(ValueError):
    """Built-in accounts cannot be removed."""


class UnknownUserError(KeyError):
    """No user with that username exists."""

    def __str__(self) -> str:  # KeyError repr-quotes its message; keep it plain.
        return self.args[0] if self.args else ""


@dataclass(frozen=True)
class UserRecord:
    username: str
    role: str
    builtin: bool
    password_hash: str | None
    created_at: str | None

    def to_public_dict(self) -> dict:
        """API-facing shape — never exposes the password hash."""
        return {
            "username": self.username,
            "role": self.role,
            "builtin": self.builtin,
            "createdAt": self.created_at,
        }


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{_HASH_SCHEME}${_PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"


def verify_password(password: str, stored: str) -> bool:
    parts = (stored or "").split("$")
    if len(parts) != 4 or parts[0] != _HASH_SCHEME:
        return False
    try:
        iterations = int(parts[1])
        salt = base64.urlsafe_b64decode(parts[2].encode("ascii"))
        expected = base64.urlsafe_b64decode(parts[3].encode("ascii"))
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def _builtin_records() -> dict[str, UserRecord]:
    return {
        name: UserRecord(
            username=name,
            role=_BUILTIN_ROLES[name],
            builtin=True,
            password_hash=None,
            created_at=None,
        )
        for name in BUILTIN_USERNAMES
    }


class UserStore:
    """File-backed user registry with an mtime cache.

    Token verification consults the store on every request, so reads are
    served from cache until the file changes on disk.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache_mtime_ns: int | None = None
        self._cache: dict[str, UserRecord] | None = None

    def list_users(self) -> list[UserRecord]:
        return list(self._load().values())

    def get(self, username: str) -> UserRecord | None:
        return self._load().get((username or "").strip().lower())

    def add(self, username: str, password: str, role: str) -> UserRecord:
        normalized = (username or "").strip().lower()
        if not _USERNAME_RE.match(normalized):
            raise ValueError(
                "Username must be 1-32 characters: lowercase letters, digits, '.', '_' or '-'."
            )
        if role not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(VALID_ROLES)}.")
        if len(password or "") < _MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters.")
        users = self._load()
        if normalized in users:
            raise DuplicateUserError(f"User '{normalized}' already exists.")
        record = UserRecord(
            username=normalized,
            role=role,
            builtin=False,
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        users[normalized] = record
        self._save(users)
        return record

    def remove(self, username: str) -> None:
        normalized = (username or "").strip().lower()
        users = self._load()
        record = users.get(normalized)
        if record is None:
            raise UnknownUserError(f"User '{normalized}' does not exist.")
        if record.builtin:
            raise BuiltinUserError(f"Built-in account '{normalized}' cannot be removed.")
        del users[normalized]
        self._save(users)

    def _load(self) -> dict[str, UserRecord]:
        try:
            mtime_ns = os.stat(self._path).st_mtime_ns
        except OSError:
            mtime_ns = None
        if self._cache is not None and mtime_ns == self._cache_mtime_ns:
            return dict(self._cache)
        users = _builtin_records()
        if mtime_ns is not None:
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Corrupt or unreadable users file: {self._path}") from exc
            for raw in payload.get("users", []):
                name = str(raw.get("username") or "").strip().lower()
                if not name:
                    continue
                builtin = name in BUILTIN_USERNAMES
                users[name] = UserRecord(
                    username=name,
                    # Built-in identities are authoritative in code, not on disk.
                    role=_BUILTIN_ROLES[name] if builtin else str(raw.get("role") or ROLE_GUEST),
                    builtin=builtin,
                    password_hash=None if builtin else raw.get("passwordHash"),
                    created_at=raw.get("createdAt"),
                )
        self._cache = dict(users)
        self._cache_mtime_ns = mtime_ns
        return users

    def _save(self, users: dict[str, UserRecord]) -> None:
        payload = {
            "version": 1,
            "users": [
                {
                    "username": record.username,
                    "role": record.role,
                    "builtin": record.builtin,
                    "passwordHash": record.password_hash,
                    "createdAt": record.created_at,
                }
                for record in users.values()
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._path)
        self._cache = dict(users)
        try:
            self._cache_mtime_ns = os.stat(self._path).st_mtime_ns
        except OSError:
            self._cache_mtime_ns = None


def storage_root() -> Path:
    configured = os.getenv("DASHBOARD_CHAT_STORAGE_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(".openbench").resolve()


_STORES: dict[Path, UserStore] = {}


def get_user_store() -> UserStore:
    """Store for the current storage root (cached per path — tests swap roots)."""
    path = storage_root() / _USERS_FILENAME
    store = _STORES.get(path)
    if store is None:
        store = UserStore(path)
        _STORES[path] = store
    return store
