"""Local two-account auth for Controlled Source Chat.

No cloud dependency: two fixed accounts (``admin`` and ``guest``) with
env-overridable passwords, and stateless HMAC-signed bearer tokens
(``username.expiry.signature``). Stateless tokens survive uvicorn
``--reload`` restarts, which the demo runner uses — an in-memory token
table would log everyone out on every source-code edit.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

ROLE_ADMIN = "admin"
ROLE_GUEST = "guest"

_TOKEN_TTL_SECONDS = 24 * 60 * 60
_SECRET_FILENAME = "controlled-auth-secret.txt"


@dataclass(frozen=True)
class Account:
    username: str
    role: str


_ACCOUNTS: dict[str, str] = {
    "admin": ROLE_ADMIN,
    "guest": ROLE_GUEST,
}

_PASSWORD_ENV = {
    "admin": ("CONTROLLED_CHAT_ADMIN_PASSWORD", "admin123"),
    "guest": ("CONTROLLED_CHAT_GUEST_PASSWORD", "guest123"),
}


def _password_for(username: str) -> str | None:
    env = _PASSWORD_ENV.get(username)
    if env is None:
        return None
    name, default = env
    return os.getenv(name, "").strip() or default


def _storage_root() -> Path:
    configured = os.getenv("GENERAL_CHAT_STORAGE_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(".openbench").resolve()


def _auth_secret() -> bytes:
    """Return the HMAC signing secret, creating and persisting one if needed."""
    configured = os.getenv("CONTROLLED_CHAT_AUTH_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    secret_file = _storage_root() / _SECRET_FILENAME
    if secret_file.is_file():
        stored = secret_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored.encode("utf-8")
    secret = secrets.token_urlsafe(32)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(secret, encoding="utf-8")
    return secret.encode("utf-8")


def _sign(payload: str) -> str:
    digest = hmac.new(_auth_secret(), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_credentials(username: str, password: str) -> Account | None:
    """Return the account when the username/password pair is valid."""
    normalized = (username or "").strip().lower()
    role = _ACCOUNTS.get(normalized)
    expected = _password_for(normalized)
    if role is None or expected is None:
        return None
    if not hmac.compare_digest((password or "").encode("utf-8"), expected.encode("utf-8")):
        return None
    return Account(username=normalized, role=role)


def issue_token(account: Account, *, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> str:
    """Mint a stateless bearer token: ``username.expiry.signature``."""
    expiry = int(time.time()) + ttl_seconds
    payload = f"{account.username}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str) -> Account | None:
    """Return the account for a valid, unexpired token; ``None`` otherwise."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        return None
    username, expiry_raw, signature = parts
    payload = f"{username}.{expiry_raw}"
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        expiry = int(expiry_raw)
    except ValueError:
        return None
    if expiry < time.time():
        return None
    role = _ACCOUNTS.get(username)
    if role is None:
        return None
    return Account(username=username, role=role)


def resolve_bearer(authorization_header: str) -> Account | None:
    """Resolve an ``Authorization: Bearer <token>`` header to an account."""
    scheme, _, token = (authorization_header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return verify_token(token.strip())
