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
