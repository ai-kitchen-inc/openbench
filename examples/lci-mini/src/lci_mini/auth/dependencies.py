"""FastAPI auth dependencies for lci-mini.

Exports :func:`verify_firebase_token`, a FastAPI dependency that
returns a :class:`FirebaseUser` on every request to a protected
endpoint. Three behaviors depending on the active :class:`AuthConfig`
mode:

- ``disabled`` — returns a synthetic ``FirebaseUser(uid="dev", ...)``
  without touching Firebase. Intended for local dev.
- ``firebase`` — reads the ``Authorization: Bearer <token>`` header,
  calls :class:`FirebaseIDVerifier`, maps verification errors to
  HTTP 401.
- ``none`` — returns a synthetic ``FirebaseUser(uid="anonymous")``.
  Matches pre-auth behavior so existing endpoints continue to work
  without changes.

The verifier instance is cached in a module-level singleton so the
Firebase Admin app is built once per process.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, status

from lci_mini.auth.config import AuthConfig

if TYPE_CHECKING:
    from openbench.integrations.firebase_auth import (
        FirebaseIDVerifier,
        FirebaseUser,
    )


__all__ = ["verify_firebase_token"]


_DEV_USER_UID = "dev"
_ANONYMOUS_USER_UID = "anonymous"

_verifier_lock = threading.Lock()
_verifier_singleton: FirebaseIDVerifier | None = None
_verifier_config_hash: tuple[str | None, str | None] | None = None


def _get_verifier(config: AuthConfig) -> FirebaseIDVerifier:
    """Return a process-wide :class:`FirebaseIDVerifier` for this config.

    Rebuilds if the underlying env (project_id + credentials path) has
    changed — tests exercise that path by monkey-patching environ.
    """
    global _verifier_singleton, _verifier_config_hash
    key = (config.firebase_project_id, config.firebase_admin_credentials)
    with _verifier_lock:
        if _verifier_singleton is None or _verifier_config_hash != key:
            from openbench.integrations.firebase_auth import FirebaseIDVerifier

            assert config.firebase_project_id is not None
            _verifier_singleton = FirebaseIDVerifier(
                project_id=config.firebase_project_id,
                service_account_file=config.firebase_admin_credentials,
            )
            _verifier_config_hash = key
        return _verifier_singleton


def _synthetic_user(uid: str) -> FirebaseUser:
    from openbench.integrations.firebase_auth import FirebaseUser as _U

    return _U(
        uid=uid,
        email=None,
        name=None,
        email_verified=False,
        raw_claims={"synthetic": True, "uid": uid},
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Return the token portion of an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def verify_firebase_token(
    authorization: str | None = Header(None),
) -> FirebaseUser:
    """FastAPI dependency returning the authenticated user for a request.

    Behavior depends on the :class:`AuthConfig` loaded from the
    environment at call time:

    - ``disabled`` → synthetic ``FirebaseUser(uid="dev")``; no header
      required. Development only — guarded against accidental prod use
      by :meth:`AuthConfig.from_env`.
    - ``firebase`` → read ``Authorization: Bearer <token>`` and verify.
      Missing header or verification failure → HTTP 401.
    - ``none`` → synthetic anonymous user; keeps legacy behavior.
    """
    config = AuthConfig.from_env()

    if config.mode == "disabled":
        return _synthetic_user(_DEV_USER_UID)

    if config.mode == "none":
        return _synthetic_user(_ANONYMOUS_USER_UID)

    # config.mode == "firebase"
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token in Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Lazy import so the dependency module itself loads without the
    # [firebase] extras — useful when only "disabled" / "none" modes
    # are active.
    from openbench.integrations.firebase_auth import (
        InvalidTokenError,
        TokenExpiredError,
        TokenRevokedError,
        WrongProjectError,
    )

    try:
        return _get_verifier(config).verify(token)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token expired",
            headers={"WWW-Authenticate": "Bearer error=invalid_token"},
        ) from exc
    except TokenRevokedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token revoked",
            headers={"WWW-Authenticate": "Bearer error=invalid_token"},
        ) from exc
    except WrongProjectError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token issued for a different Firebase project",
            headers={"WWW-Authenticate": "Bearer error=invalid_token"},
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid ID token",
            headers={"WWW-Authenticate": "Bearer error=invalid_token"},
        ) from exc
