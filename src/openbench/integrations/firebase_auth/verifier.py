"""Firebase ID token verification.

Wraps :mod:`firebase_admin.auth` with an ergonomic Python class:

- Single :class:`FirebaseIDVerifier` holds the Firebase Admin app handle
- :meth:`FirebaseIDVerifier.verify` validates a token and returns a
  :class:`FirebaseUser`, or raises one of the typed errors below
- Specific error classes (:class:`TokenExpiredError`,
  :class:`TokenRevokedError`, :class:`WrongProjectError`,
  :class:`InvalidTokenError`) let callers render different UX for each
  failure mode without inspecting error messages

The Firebase Admin SDK is imported **lazily** so that modules importing
this file do not require ``[firebase]`` extras; only calling
:meth:`FirebaseIDVerifier.verify` (or passing an admin credential path
on construction) touches the dependency.

Example:
    >>> from openbench.integrations.firebase_auth import FirebaseIDVerifier
    >>> verifier = FirebaseIDVerifier(
    ...     project_id="my-project",
    ...     service_account_file="/secrets/firebase-admin.json",
    ... )
    >>> user = verifier.verify(bearer_token)
    >>> user.uid
    'NQaK3a...firebase-user-id'
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "FirebaseIDVerifier",
    "FirebaseUser",
    "InvalidTokenError",
    "TokenExpiredError",
    "TokenRevokedError",
    "WrongProjectError",
]


def _missing_dep_message() -> str:
    return (
        "FirebaseIDVerifier requires the 'firebase' extras. Install with:\n"
        "    pip install openbench[firebase]\n"
        "which pulls firebase-admin."
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvalidTokenError(Exception):
    """Base exception for any ID token verification failure."""


class TokenExpiredError(InvalidTokenError):
    """The token's ``exp`` claim is in the past."""


class TokenRevokedError(InvalidTokenError):
    """The token was revoked by the Firebase Auth admin."""


class WrongProjectError(InvalidTokenError):
    """The token's ``aud`` claim does not match the configured project id."""


# ---------------------------------------------------------------------------
# FirebaseUser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FirebaseUser:
    """Authenticated user as produced by :class:`FirebaseIDVerifier`.

    Attributes:
        uid: Firebase user id. Stable across sign-ins; use as your
            primary key for per-user data.
        email: User's email address. ``None`` for phone-only providers.
        name: Display name from the Google / social provider. Optional.
        email_verified: True if Firebase says the email is verified.
            Unreliable — phone-only users may have ``False`` even if
            they are legitimately authenticated.
        raw_claims: Full decoded JWT body for advanced use (custom
            claims, provider-specific fields).
    """

    uid: str
    email: str | None = None
    name: str | None = None
    email_verified: bool = False
    raw_claims: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class FirebaseIDVerifier:
    """Verify Firebase ID tokens against a configured project.

    Thread-safe — the Firebase Admin app handle is built once on first
    use and reused for every subsequent verification. Calls to
    :meth:`verify` only hit the network the first time Firebase's
    public keys are fetched (the admin SDK caches them).

    Construction is network-free: the Firebase Admin app is built
    lazily on first :meth:`verify` call.
    """

    def __init__(
        self,
        project_id: str,
        *,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
        app_name: str = "openbench-verifier",
    ):
        if not project_id:
            raise ValueError("project_id must be a non-empty string")
        self.project_id = project_id
        self._service_account_file = (
            str(service_account_file) if service_account_file is not None else None
        )
        self._explicit_credentials = credentials
        self._app_name = app_name
        self._app: Any = None
        self._app_lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def verify(self, id_token: str, *, check_revoked: bool = True) -> FirebaseUser:
        """Validate an ID token and return the authenticated user.

        Args:
            id_token: Raw JWT from the client's ``Authorization`` header.
            check_revoked: When True, additionally consult Firebase to
                ensure the token has not been revoked by an admin. Adds
                one network call per verify; disable for high-throughput
                endpoints if you can tolerate a few seconds of staleness.

        Returns:
            :class:`FirebaseUser` with uid + claims.

        Raises:
            InvalidTokenError: Token is structurally invalid / wrong
                signature / malformed.
            TokenExpiredError: Token's ``exp`` claim has passed.
            TokenRevokedError: Token was revoked.
            WrongProjectError: Token's ``aud`` does not match
                ``self.project_id``.
        """
        if not id_token:
            raise InvalidTokenError("id_token is empty")

        auth = self._get_auth_module()
        # Reference the specific exception types lazily so the module
        # doesn't have to import them at the top and create a hard
        # dependency on firebase_admin.
        fb_errors = self._get_firebase_errors()

        try:
            claims = auth.verify_id_token(
                id_token,
                app=self._get_app(),
                check_revoked=check_revoked,
            )
        except fb_errors.ExpiredIdTokenError as exc:
            raise TokenExpiredError(str(exc)) from exc
        except fb_errors.RevokedIdTokenError as exc:
            raise TokenRevokedError(str(exc)) from exc
        except fb_errors.InvalidIdTokenError as exc:
            message = str(exc)
            # Firebase raises the same InvalidIdTokenError for wrong-
            # project tokens; recognize that signal and surface a more
            # actionable exception class.
            if "audience" in message.lower() or "aud" in message.lower():
                raise WrongProjectError(message) from exc
            raise InvalidTokenError(message) from exc
        except ValueError as exc:
            # Raised for malformed / non-JWT input by google-auth layer.
            raise InvalidTokenError(str(exc)) from exc

        return self._claims_to_user(claims)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _claims_to_user(claims: dict[str, Any]) -> FirebaseUser:
        """Pick the user-facing fields out of the full decoded JWT."""
        return FirebaseUser(
            uid=str(claims.get("uid") or claims.get("sub") or ""),
            email=claims.get("email"),
            name=claims.get("name"),
            email_verified=bool(claims.get("email_verified", False)),
            raw_claims=dict(claims),
        )

    def _get_app(self) -> Any:
        """Return the Firebase Admin app, building it on first call."""
        if self._app is not None:
            return self._app
        with self._app_lock:
            if self._app is None:
                self._app = self._build_app()
            return self._app

    def _build_app(self) -> Any:
        """Construct a :class:`firebase_admin.App` with an explicit name.

        Using a unique ``app_name`` prevents collisions with any
        :func:`firebase_admin.initialize_app` call the host application
        may have made (Firebase's default app is a global singleton).
        """
        try:
            import firebase_admin
            from firebase_admin import credentials as fb_credentials
        except ImportError as exc:
            raise ImportError(_missing_dep_message()) from exc

        creds = self._explicit_credentials
        if creds is None and self._service_account_file is not None:
            creds = fb_credentials.Certificate(self._service_account_file)
        # Falling through with ``creds=None`` lets firebase-admin pick
        # up Application Default Credentials — matches the pattern
        # used by Cloud Run / GKE deployments.
        options = {"projectId": self.project_id} if self.project_id else None
        try:
            return firebase_admin.initialize_app(
                credential=creds,
                options=options,
                name=self._app_name,
            )
        except ValueError as exc:
            # Already initialized under this name — reuse the existing app.
            if "already exists" in str(exc).lower():
                return firebase_admin.get_app(self._app_name)
            raise

    @staticmethod
    def _get_auth_module() -> Any:
        try:
            from firebase_admin import auth
        except ImportError as exc:
            raise ImportError(_missing_dep_message()) from exc
        return auth

    @staticmethod
    def _get_firebase_errors() -> Any:
        """Return a namespace holding the Firebase auth exception classes."""
        try:
            from firebase_admin import auth
        except ImportError as exc:
            raise ImportError(_missing_dep_message()) from exc
        return auth

    def __repr__(self) -> str:
        return f"FirebaseIDVerifier(project_id={self.project_id!r})"
