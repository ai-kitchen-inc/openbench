"""Environment-driven auth configuration for lci-mini.

Three distinct modes are supported at startup, selected by env vars:

1. ``disabled``  — ``OPENBENCH_AUTH_DISABLED=1``; the dependency
   short-circuits to a synthetic dev user. Use for local dev so you
   don't need a real Firebase project.
2. ``firebase``  — ``FIREBASE_PROJECT_ID`` set; the dependency
   verifies Firebase ID tokens via the admin SDK.
3. ``none``      — no env flag; the dependency is a no-op (returns
   an anonymous user). Matches today's behavior and keeps backward
   compat with service-account deployments.

The two flags are **mutually exclusive**: setting both
``OPENBENCH_AUTH_DISABLED=1`` and ``FIREBASE_PROJECT_ID`` raises on
startup to prevent accidentally shipping dev bypass to production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthConfig:
    """Immutable auth configuration loaded from the environment."""

    mode: str  # "disabled" | "firebase" | "none"
    firebase_project_id: str | None = None
    firebase_admin_credentials: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AuthConfig:
        """Build config from process env (or an explicit mapping for tests)."""
        e = env if env is not None else os.environ
        disabled_flag = (e.get("OPENBENCH_AUTH_DISABLED") or "").strip().lower()
        disabled = disabled_flag in ("1", "true", "yes")
        project_id = (e.get("FIREBASE_PROJECT_ID") or "").strip() or None

        if disabled and project_id:
            raise RuntimeError(
                "OPENBENCH_AUTH_DISABLED=1 cannot be combined with "
                "FIREBASE_PROJECT_ID. Pick one — dev bypass or real Firebase."
            )
        if disabled:
            return cls(mode="disabled")
        if project_id:
            creds = (e.get("FIREBASE_ADMIN_CREDENTIALS") or "").strip() or None
            return cls(
                mode="firebase",
                firebase_project_id=project_id,
                firebase_admin_credentials=creds,
            )
        return cls(mode="none")


@dataclass(frozen=True)
class DriveOAuthConfig:
    """Config for the /auth/drive/* endpoint family.

    ``enabled`` is False when ``GOOGLE_OAUTH_CLIENT_SECRETS`` is unset —
    the endpoints then return 501 rather than breaking startup. This
    keeps the identity-only (M1) deployment path viable.
    """

    enabled: bool
    client_secrets_path: str | None = None
    redirect_url: str | None = None
    scopes: tuple[str, ...] = ()
    session_secret: str | None = None
    token_encryption_key_env: str = "DRIVE_TOKEN_ENCRYPTION_KEY"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> DriveOAuthConfig:
        e = env if env is not None else os.environ
        secrets_path = (e.get("GOOGLE_OAUTH_CLIENT_SECRETS") or "").strip() or None
        if not secrets_path:
            return cls(enabled=False)
        redirect = (e.get("DRIVE_OAUTH_REDIRECT_URL") or "").strip()
        if not redirect:
            raise RuntimeError(
                "GOOGLE_OAUTH_CLIENT_SECRETS is set but DRIVE_OAUTH_REDIRECT_URL is not. "
                "Both are required to enable the Drive OAuth flow."
            )
        scopes_raw = (e.get("DRIVE_OAUTH_SCOPES") or "").strip()
        scopes = (
            tuple(s for s in scopes_raw.split(",") if s.strip())
            if scopes_raw
            else ("https://www.googleapis.com/auth/drive.file",)
        )
        session_secret = (e.get("SESSION_SECRET") or "").strip() or None
        if not session_secret:
            raise RuntimeError(
                "SESSION_SECRET is required when the Drive OAuth flow is enabled. "
                "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return cls(
            enabled=True,
            client_secrets_path=secrets_path,
            redirect_url=redirect,
            scopes=scopes,
            session_secret=session_secret,
        )
