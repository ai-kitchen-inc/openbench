"""Local auth for Controlled Source Chat.

No cloud dependency: accounts live in the persistent user store (see
:mod:`controlled_source_chat.users`) — built-in ``admin`` and ``guest``
with env-overridable passwords plus any admin-created users — and
stateless HMAC-signed bearer tokens (``username.expiry.signature``).
Stateless tokens survive uvicorn ``--reload`` restarts, which the demo
runner uses — an in-memory token table would log everyone out on every
source-code edit. Token verification re-checks the store, so removing
a user revokes their unexpired tokens immediately.
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

from controlled_source_chat.users import ROLE_ADMIN, ROLE_GUEST, get_user_store, verify_password

_TOKEN_TTL_SECONDS = 24 * 60 * 60
_SECRET_FILENAME = "controlled-auth-secret.txt"


@dataclass(frozen=True)
class Account:
    username: str
    role: str


_PASSWORD_ENV = {
    "admin": ("CONTROLLED_CHAT_ADMIN_PASSWORD", "admin123"),
    "guest": ("CONTROLLED_CHAT_GUEST_PASSWORD", "guest123"),
}


ALLOW_DEFAULT_PASSWORDS_ENV = "CONTROLLED_CHAT_ALLOW_DEFAULT_PASSWORDS"


def _is_deployed() -> bool:
    """True inside a deployed image rather than a local demo run.

    Cloud Run sets ``K_SERVICE``; the container image bakes in
    ``GENERAL_CHAT_STATIC_DIR``. Neither is set by ``openbench demo run``.
    """
    return bool(os.getenv("K_SERVICE", "").strip() or os.getenv("GENERAL_CHAT_STATIC_DIR", "").strip())


def _default_passwords_allowed() -> bool:
    """Whether the well-known demo passwords may be used.

    They are published in the README, so on a reachable deployment they are
    no protection at all: the admin account can register MCP servers, which
    run commands on the host. Local demo runs keep them; a deployment must
    set real passwords (or opt in explicitly with
    ``CONTROLLED_CHAT_ALLOW_DEFAULT_PASSWORDS=1``).
    """
    if os.getenv(ALLOW_DEFAULT_PASSWORDS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return not _is_deployed()


def _password_for(username: str) -> str | None:
    """Return the built-in account's password, or None when it cannot log in."""
    env = _PASSWORD_ENV.get(username)
    if env is None:
        return None
    name, default = env
    configured = os.getenv(name, "").strip()
    if _default_passwords_allowed():
        return configured or default
    # Deployed: only an operator-chosen value counts, and the published
    # default is refused even when it was set explicitly.
    if not configured or configured == default:
        return None
    return configured


def assert_password_posture() -> None:
    """Refuse to start a deployment whose admin account has no real password.

    Raises:
        RuntimeError: Deployed, default passwords not opted into, and
            ``CONTROLLED_CHAT_ADMIN_PASSWORD`` is unset or the demo default.
    """
    if _password_for("admin") is None:
        raise RuntimeError(
            "Refusing to start: this is a deployed Controlled Source Chat image and "
            "CONTROLLED_CHAT_ADMIN_PASSWORD is unset or still the published demo default. "
            "Set a real admin password (and CONTROLLED_CHAT_GUEST_PASSWORD to enable the "
            f"guest account), or set {ALLOW_DEFAULT_PASSWORDS_ENV}=1 to accept the risk."
        )


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
    record = get_user_store().get(normalized)
    if record is None:
        return None
    if record.password_hash is None:
        # Built-in account: password comes from env override or default.
        expected = _password_for(normalized)
        if expected is None or not hmac.compare_digest(
            (password or "").encode("utf-8"), expected.encode("utf-8")
        ):
            return None
    elif not verify_password(password or "", record.password_hash):
        return None
    return Account(username=normalized, role=record.role)


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
    # Store lookup is the revocation point: a removed user's unexpired
    # token dies here, and role changes take effect immediately.
    record = get_user_store().get(username)
    if record is None:
        return None
    return Account(username=username, role=record.role)


def resolve_bearer(authorization_header: str) -> Account | None:
    """Resolve an ``Authorization: Bearer <token>`` header to an account."""
    scheme, _, token = (authorization_header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return verify_token(token.strip())
