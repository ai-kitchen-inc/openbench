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
        "FirebaseIDVerifier (check_revoked=True) requires firebase-admin. "
        "Install with: pip install openbench[firebase]"
    )


def _missing_google_auth_message() -> str:
    return (
        "FirebaseIDVerifier's default verify path requires google-auth. "
        "Install with: pip install google-auth"
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

    def verify(self, id_token: str, *, check_revoked: bool = False) -> FirebaseUser:
        """Validate an ID token and return the authenticated user.

        Uses the public ``google.oauth2.id_token`` verifier by default —
        it fetches Firebase's public signing keys from a well-known URL
        and verifies the JWT locally, **without** requiring any
        credentials. Works on localhost with zero setup.

        When ``check_revoked=True`` is passed, falls back to the
        Firebase Admin SDK so it can additionally consult Firebase to
        see whether the user's tokens have been revoked. That path
        requires either an explicit service-account file
        (:attr:`_service_account_file`) or Application Default
        Credentials to be set up in the environment.

        Args:
            id_token: Raw JWT from the client's ``Authorization`` header.
            check_revoked: When True, use the Admin SDK to check token
                revocation. Adds one network call and a credentials
                requirement. Defaults to False.

        Returns:
            :class:`FirebaseUser` with uid + claims.

        Raises:
            InvalidTokenError: Token is structurally invalid / wrong
                signature / malformed.
            TokenExpiredError: Token's ``exp`` claim has passed.
            TokenRevokedError: Token was revoked (only raised when
                ``check_revoked=True``).
            WrongProjectError: Token's ``aud`` does not match
                ``self.project_id``.
        """
        if not id_token:
            raise InvalidTokenError("id_token is empty")

        if check_revoked:
            return self._verify_via_admin_sdk(id_token)
        return self._verify_via_google_auth(id_token)

    # ------------------------------------------------------------------ paths

    def _verify_via_google_auth(self, id_token: str) -> FirebaseUser:
        """Lightweight path — uses google-auth's JWKS-based verifier.

        No credentials required. Validates signature, expiry, issuer,
        and audience (``self.project_id``). Cannot detect revocation;
        use :meth:`_verify_via_admin_sdk` for that.
        """
        try:
            from google.auth.exceptions import GoogleAuthError
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
        except ImportError as exc:
            raise ImportError(_missing_google_auth_message()) from exc

        try:
            claims = google_id_token.verify_firebase_token(
                id_token,
                google_requests.Request(),
                audience=self.project_id,
            )
        except ValueError as exc:
            message = str(exc)
            lower = message.lower()
            if "expired" in lower:
                raise TokenExpiredError(message) from exc
            if "audience" in lower or "aud" in lower or "project" in lower:
                raise WrongProjectError(message) from exc
            raise InvalidTokenError(message) from exc
        except GoogleAuthError as exc:
            raise InvalidTokenError(str(exc)) from exc
        return self._claims_to_user(claims)

    def _verify_via_admin_sdk(self, id_token: str) -> FirebaseUser:
        """Heavy path — uses firebase-admin's ``verify_id_token``.

        Supports ``check_revoked=True``. Requires credentials (service
        account file OR Application Default Credentials).
        """
        auth = self._get_auth_module()
        fb_errors = self._get_firebase_errors()

        try:
            claims = auth.verify_id_token(
                id_token,
                app=self._get_app(),
                check_revoked=True,
            )
        except fb_errors.ExpiredIdTokenError as exc:
            raise TokenExpiredError(str(exc)) from exc
        except fb_errors.RevokedIdTokenError as exc:
            raise TokenRevokedError(str(exc)) from exc
        except fb_errors.InvalidIdTokenError as exc:
            message = str(exc)
            if "audience" in message.lower() or "aud" in message.lower():
                raise WrongProjectError(message) from exc
            raise InvalidTokenError(message) from exc
        except ValueError as exc:
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
