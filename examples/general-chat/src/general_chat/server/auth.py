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


async def require_firebase_user(request: Request) -> FirebaseUser:
    """Verify the request's Firebase ID token and email allowlist."""
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
