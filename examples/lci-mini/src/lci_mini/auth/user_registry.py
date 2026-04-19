"""User registry + approval gate — Path A (backend auto-disable).

On first sign-in, this module:

1. Upserts a ``users/{uid}`` document in Firestore with profile metadata
   (email, display name, photo, provider, timestamps, sign-in count).
2. Unless the user's email is in ``AUTH_BOOTSTRAP_EMAILS`` (the trusted
   admin list), calls Firebase Admin SDK to set
   ``disabled=true`` on the Auth record. The next request from that
   user (with ``check_revoked=True`` in the verifier) gets 401.
3. Raises :class:`PendingApprovalError` so the caller can return a 403
   with a machine-readable ``detail: "pending_approval"`` so the
   frontend redirects to the pending-approval screen.

Admin approval flow:

- Admin opens Firebase Console → Authentication → Users
- Sees the new user marked **Disabled**
- Clicks **Enable account** → done
- Next time the user signs in, they pass verify and can use the app.

Why this shape: the Admin Console's built-in Disable/Enable toggle
is the admin UI. Zero custom dashboard needed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lci_mini.auth.config import AuthConfig

if TYPE_CHECKING:
    from openbench.integrations.firebase_auth import FirebaseUser

logger = logging.getLogger(__name__)

__all__ = [
    "PendingApprovalError",
    "UserRegistry",
    "get_user_registry",
    "reset_user_registry_for_tests",
]


class PendingApprovalError(Exception):
    """Raised when a verified user has not yet been approved by an admin.

    The caller (FastAPI dependency) translates this into a 403 with
    ``detail: "pending_approval"`` so the frontend can show the
    "Contact admin" screen without guessing based on error messages.
    """

    def __init__(self, uid: str, email: str | None = None) -> None:
        self.uid = uid
        self.email = email
        super().__init__(
            f"Account {email or uid} is pending admin approval"
        )


@dataclass(frozen=True)
class _Collections:
    users: str = "users"


class UserRegistry:
    """Process-wide singleton that tracks users + gates new ones.

    Lazy — does nothing until :meth:`ensure` is called. Thread-safe;
    uses a lock around the Firestore client build and a seen-UIDs
    cache to avoid re-upserting on every request.
    """

    def __init__(self, *, firebase_admin_app: Any, cfg: AuthConfig) -> None:
        self._app = firebase_admin_app
        self._cfg = cfg
        # In-process cache of UIDs we've already welcomed this process.
        # The ``lastSeenAt`` update still runs on every request — the
        # cache only skips the disable / create work that only matters
        # on the very first sign-in.
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()
        self._collections = _Collections()
        self._firestore: Any = None
        self._auth_admin: Any = None
        self._client_lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def ensure(self, user: FirebaseUser) -> None:
        """Enforce the approval flow for ``user``.

        Raises :class:`PendingApprovalError` when the user is not yet
        approved. Returns quietly when:
            - user is already approved (i.e. not disabled in Firebase)
            - user's email is in the bootstrap list (skip disable step)
            - Firestore / Admin SDK are unavailable (graceful degrade)
        """
        try:
            is_first_time = self._upsert_profile(user)
        except Exception:
            # Upsert failure must not block a legitimately-approved user.
            logger.exception("users/%s upsert failed; continuing", user.uid)
            return

        if not is_first_time:
            return

        email_lc = (user.email or "").strip().lower()
        if email_lc and email_lc in self._cfg.bootstrap_emails:
            logger.info(
                "bootstrap email %s — skipping auto-disable, auto-approving",
                email_lc,
            )
            return

        # First sign-in and not a bootstrap admin — disable until an
        # admin flips the toggle in Firebase Console.
        try:
            self._disable_auth_user(user.uid)
        except Exception:
            # Don't leak internals to the client but leave a breadcrumb.
            logger.exception("failed to disable new user %s; letting them in", user.uid)
            return
        raise PendingApprovalError(user.uid, user.email)

    # ---------------------------------------------------------------- internal

    def _upsert_profile(self, user: FirebaseUser) -> bool:
        """Write users/{uid} and return True when this is the first sign-in.

        "First sign-in" means either the doc didn't exist yet in
        Firestore OR we've never seen this UID in this process. The
        process cache is a fast path; Firestore is the source of truth
        because the process cache is lost on restart.
        """
        now = datetime.now(timezone.utc)
        doc_ref = self._users_collection().document(user.uid)

        # Fast-path: if we've already greeted this uid this process,
        # just bump lastSeenAt + signInCount. No disable logic.
        with self._seen_lock:
            already_seen_in_process = user.uid in self._seen

        if already_seen_in_process:
            doc_ref.set(
                {
                    "uid": user.uid,
                    "email": user.email,
                    "displayName": user.name,
                    "lastSeenAt": now.isoformat(),
                },
                merge=True,
            )
            return False

        # Slow path: read Firestore to determine whether the doc already
        # exists (survives process restarts — don't re-disable users who
        # already got approved before we rebooted).
        snapshot = doc_ref.get()
        existed = snapshot.exists

        if existed:
            # Bump lastSeenAt + signInCount. Keep createdAt untouched.
            existing = snapshot.to_dict() or {}
            sign_in_count = int(existing.get("signInCount") or 0) + 1
            doc_ref.set(
                {
                    "uid": user.uid,
                    "email": user.email,
                    "displayName": user.name,
                    "photoURL": (user.raw_claims or {}).get("picture"),
                    "provider": self._primary_provider(user),
                    "lastSeenAt": now.isoformat(),
                    "signInCount": sign_in_count,
                },
                merge=True,
            )
        else:
            # Brand new user — record everything + createdAt.
            doc_ref.set(
                {
                    "uid": user.uid,
                    "email": user.email,
                    "displayName": user.name,
                    "photoURL": (user.raw_claims or {}).get("picture"),
                    "provider": self._primary_provider(user),
                    "createdAt": now.isoformat(),
                    "lastSeenAt": now.isoformat(),
                    "signInCount": 1,
                }
            )

        with self._seen_lock:
            self._seen.add(user.uid)

        return not existed

    def _disable_auth_user(self, uid: str) -> None:
        auth = self._get_auth_admin()
        auth.update_user(uid, disabled=True, app=self._app)
        logger.info("auto-disabled new user %s pending admin approval", uid)

    def _users_collection(self) -> Any:
        return self._get_firestore().collection(self._collections.users)

    def _get_firestore(self) -> Any:
        if self._firestore is not None:
            return self._firestore
        with self._client_lock:
            if self._firestore is None:
                from firebase_admin import firestore

                self._firestore = firestore.client(app=self._app)
            return self._firestore

    def _get_auth_admin(self) -> Any:
        if self._auth_admin is not None:
            return self._auth_admin
        with self._client_lock:
            if self._auth_admin is None:
                from firebase_admin import auth as _auth

                self._auth_admin = _auth
            return self._auth_admin

    @staticmethod
    def _primary_provider(user: FirebaseUser) -> str | None:
        """Pull the primary sign-in provider id from the raw claims."""
        claims = user.raw_claims or {}
        firebase_claim = claims.get("firebase") or {}
        providers = firebase_claim.get("sign_in_provider")
        if isinstance(providers, str):
            return providers
        return None


# ---------------------------------------------------------------------------
# Singleton — built lazily on first request
# ---------------------------------------------------------------------------


_registry_singleton: UserRegistry | None = None
_registry_lock = threading.Lock()


def get_user_registry() -> UserRegistry | None:
    """Return the process-wide :class:`UserRegistry`, or None if unavailable.

    Returns None when:
        - auth mode != "firebase" (disabled / none)
        - no ``FIREBASE_ADMIN_CREDENTIALS`` and no ADC
        - firebase-admin isn't installed

    In all the None cases the caller silently skips the registry path —
    the same as the pre-registration behaviour.
    """
    global _registry_singleton
    if _registry_singleton is not None:
        return _registry_singleton

    cfg = AuthConfig.from_env()
    if cfg.mode != "firebase":
        return None

    with _registry_lock:
        if _registry_singleton is not None:
            return _registry_singleton
        from lci_mini.auth.drive import _build_firebase_admin_app

        app = _build_firebase_admin_app(cfg)
        if app is None:
            # No service-account creds — can't write Firestore. Skip
            # the registry entirely and let users through as before.
            logger.warning(
                "UserRegistry disabled: no FIREBASE_ADMIN_CREDENTIALS. "
                "New users will not be auto-disabled."
            )
            return None
        _registry_singleton = UserRegistry(firebase_admin_app=app, cfg=cfg)
        return _registry_singleton


def reset_user_registry_for_tests() -> None:
    """Drop the singleton so tests can swap in their own."""
    global _registry_singleton
    with _registry_lock:
        _registry_singleton = None
