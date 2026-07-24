"""Firebase auth helpers for the General Chat FastAPI app."""

from __future__ import annotations

import os
from collections.abc import Iterable
from functools import lru_cache

from fastapi import HTTPException, Request, status

from openbench.integrations.firebase_auth import (
    FirebaseIDVerifier,
    FirebaseUser,
    InvalidTokenError,
)

LOCAL_OWNER = "local"
"""Sentinel data owner used when auth is disabled (single-user local dev)."""

LOCAL_ROLE_HEADER = "X-Local-Role"
"""Request header selecting the local-dev role when auth is disabled."""

_LOCAL_ROLES = frozenset({"admin", "user"})


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def auth_enabled() -> bool:
    """Return whether General Chat should require Firebase auth."""
    if _env_flag("OPENBENCH_AUTH_DISABLED", default=False):
        return False
    return bool(os.getenv("GENERAL_CHAT_FIREBASE_PROJECT_ID"))


def allowed_emails() -> set[str]:
    """Return the configured lowercase email allowlist."""
    return _split_csv(os.getenv("GENERAL_CHAT_ALLOWED_EMAILS"))


def local_role(request: Request) -> str:
    """Local-dev role when auth is disabled: header > env > "admin".

    Lets developers see the app as a plain "user" account without any
    login — via the ``X-Local-Role`` request header (UI toggle) or the
    ``GENERAL_CHAT_LOCAL_ROLE`` env var. The middleware consults this
    ONLY on the auth-disabled branch, so the header cannot escalate or
    change roles on real (Firebase-authenticated) deployments. Invalid
    values fall back to "admin", preserving default local behavior.
    """
    header = (request.headers.get(LOCAL_ROLE_HEADER) or "").strip().lower()
    if header in _LOCAL_ROLES:
        return header
    env = (os.getenv("GENERAL_CHAT_LOCAL_ROLE") or "").strip().lower()
    return env if env in _LOCAL_ROLES else "admin"


def allowed_domains() -> set[str]:
    """Return optional lowercase email domains allowed for access."""
    return _split_csv(os.getenv("GENERAL_CHAT_ALLOWED_DOMAINS"))


@lru_cache(maxsize=1)
def _verifier() -> FirebaseIDVerifier:
    project_id = os.getenv("GENERAL_CHAT_FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        raise RuntimeError("GENERAL_CHAT_FIREBASE_PROJECT_ID is required when auth is enabled")
    service_account = os.getenv("GENERAL_CHAT_FIREBASE_SERVICE_ACCOUNT_FILE") or None
    return FirebaseIDVerifier(
        project_id=project_id,
        service_account_file=service_account,
        app_name="general-chat-verifier",
    )


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _email_allowed(email: str | None, *, emails: Iterable[str], domains: Iterable[str]) -> bool:
    if not email:
        return False
    normalized = email.strip().lower()
    if normalized in set(emails):
        return True
    _, _, domain = normalized.partition("@")
    return bool(domain and domain in set(domains))


async def require_firebase_user(request: Request, user_store=None) -> FirebaseUser:
    """Verify the request's Firebase ID token and resolve access.

    With ``user_store`` (the admin-managed account store), access and
    role come from the store: unknown email -> 403, known email ->
    ``request.state.user_role`` is set from the record. Without a
    store, the legacy env allowlist (``GENERAL_CHAT_ALLOWED_EMAILS`` /
    ``_DOMAINS``) applies — kept for wrapper apps and old tests.
    """
    token = _extract_bearer_token(request)
    try:
        user = _verifier().verify(
            token,
            check_revoked=_env_flag("GENERAL_CHAT_FIREBASE_CHECK_REVOKED", default=False),
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase ID token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if user_store is not None:
        record = user_store.get(user.email or "") if user.email else None
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not allowed for this deployment.",
            )
        request.state.firebase_user = user
        request.state.user_role = record.role
        return user

    emails = allowed_emails()
    domains = allowed_domains()
    if not emails and not domains:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No Firebase user allowlist is configured.",
        )
    if not _email_allowed(user.email, emails=emails, domains=domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firebase user is not allowed for this OpenBench deployment.",
        )

    request.state.firebase_user = user
    return user


def current_role(request: Request) -> str:
    """Return the access role for this request.

    Role is stamped on ``request.state.user_role`` by
    :func:`require_firebase_user` when a user store is in play. With
    auth disabled (local dev) or an ``owner_override`` from a wrapper
    app (which enforces its own guardrails outermost), the request is
    treated as admin. Any other authenticated request defaults to the
    least-privileged ``user`` role.
    """
    role = getattr(request.state, "user_role", None)
    if role:
        return str(role)
    if getattr(request.state, "owner_override", None) or not auth_enabled():
        return "admin"
    return "user"


def current_owner(request: Request) -> str:
    """Return the data-owner key for this request.

    The owner scopes all per-user data (sessions, sources, uploads).
    A wrapper app may pre-assign ``request.state.owner_override`` (e.g.
    a local-auth middleware mapping its own accounts to owners); that
    wins over Firebase resolution. Otherwise: lowercased email of the
    verified Firebase user, or ``LOCAL_OWNER`` when auth is disabled.
    The 401 branch is defensive — the auth middleware already rejects
    unauthenticated requests on every protected prefix before a handler
    runs.
    """
    override = getattr(request.state, "owner_override", None)
    if override:
        return str(override).strip().lower()
    user = getattr(request.state, "firebase_user", None)
    email = getattr(user, "email", None) if user is not None else None
    if email:
        return str(email).strip().lower()
    if not auth_enabled():
        return LOCAL_OWNER
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
