"""Tests for the UserRegistry approval gate (Path A: backend auto-disable).

Exercises the full lifecycle via a fake Firestore + fake Admin Auth:
first-time signin creates a doc and disables the user (unless
bootstrap), repeat signin bumps counters, and bootstrap emails bypass
the disable call entirely.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from lci_mini.auth.config import AuthConfig
from lci_mini.auth.user_registry import PendingApprovalError, UserRegistry


class FakeDoc:
    """Minimal stand-in for a Firestore DocumentReference + Snapshot pair."""

    def __init__(self) -> None:
        self._data: dict | None = None

    def get(self) -> FakeDoc:
        return self

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return dict(self._data) if self._data else None

    def set(self, data: dict, merge: bool = False) -> None:
        if merge and self._data is not None:
            self._data = {**self._data, **data}
        else:
            self._data = dict(data)


class FakeCollection:
    def __init__(self) -> None:
        self._docs: dict[str, FakeDoc] = {}

    def document(self, uid: str) -> FakeDoc:
        if uid not in self._docs:
            self._docs[uid] = FakeDoc()
        return self._docs[uid]


class FakeFirestore:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


def _make_fb_user(uid: str = "u-1", email: str = "u@example.com"):
    from openbench.integrations.firebase_auth import FirebaseUser

    return FirebaseUser(
        uid=uid,
        email=email,
        name="Test User",
        email_verified=True,
        raw_claims={
            "firebase": {"sign_in_provider": "google.com"},
            "picture": "https://lh3/p.jpg",
        },
    )


def _make_registry(
    cfg: AuthConfig | None = None,
    firestore: FakeFirestore | None = None,
) -> tuple[UserRegistry, FakeFirestore, MagicMock]:
    """Build a registry with its Firestore + Admin Auth modules swapped
    for fakes so no Firebase project is required."""
    if cfg is None:
        cfg = AuthConfig(
            mode="firebase",
            firebase_project_id="fake",
        )
    fs = firestore or FakeFirestore()
    auth_admin = MagicMock()

    registry = UserRegistry(firebase_admin_app=MagicMock(), cfg=cfg)
    # Short-circuit the real SDK imports.
    registry._firestore = fs
    registry._auth_admin = auth_admin
    return registry, fs, auth_admin


# ---------------------------------------------------------------------------
# First-time sign-in
# ---------------------------------------------------------------------------


class TestFirstTimeSignIn:
    def test_creates_firestore_doc(self):
        registry, fs, _ = _make_registry()
        user = _make_fb_user()

        with pytest.raises(PendingApprovalError):
            registry.ensure(user)

        doc = fs.collection("users").document(user.uid).to_dict()
        assert doc is not None
        assert doc["uid"] == "u-1"
        assert doc["email"] == "u@example.com"
        assert doc["signInCount"] == 1
        assert "createdAt" in doc
        assert "lastSeenAt" in doc

    def test_disables_auth_user(self):
        registry, _, auth_admin = _make_registry()
        user = _make_fb_user()

        with pytest.raises(PendingApprovalError):
            registry.ensure(user)

        auth_admin.update_user.assert_called_once()
        args, kwargs = auth_admin.update_user.call_args
        assert args[0] == "u-1"
        assert kwargs["disabled"] is True

    def test_raises_pending_approval_with_email(self):
        registry, _, _ = _make_registry()
        user = _make_fb_user(email="jane@example.com")

        with pytest.raises(PendingApprovalError) as exc_info:
            registry.ensure(user)
        assert exc_info.value.uid == "u-1"
        assert exc_info.value.email == "jane@example.com"

    def test_captures_provider_from_claims(self):
        registry, fs, _ = _make_registry()
        user = _make_fb_user()

        with pytest.raises(PendingApprovalError):
            registry.ensure(user)
        doc = fs.collection("users").document(user.uid).to_dict()
        assert doc["provider"] == "google.com"


# ---------------------------------------------------------------------------
# Bootstrap bypass
# ---------------------------------------------------------------------------


class TestBootstrapEmails:
    def test_bootstrap_email_skips_disable(self):
        cfg = AuthConfig(
            mode="firebase",
            firebase_project_id="fake",
            bootstrap_emails=frozenset({"admin@example.com"}),
        )
        registry, _, auth_admin = _make_registry(cfg=cfg)
        user = _make_fb_user(email="admin@example.com")

        # Should NOT raise and NOT call update_user.
        registry.ensure(user)
        auth_admin.update_user.assert_not_called()

    def test_bootstrap_is_case_insensitive(self):
        cfg = AuthConfig(
            mode="firebase",
            firebase_project_id="fake",
            bootstrap_emails=frozenset({"admin@example.com"}),
        )
        registry, _, auth_admin = _make_registry(cfg=cfg)
        user = _make_fb_user(email="ADMIN@Example.COM")

        registry.ensure(user)
        auth_admin.update_user.assert_not_called()

    def test_non_bootstrap_still_disabled(self):
        cfg = AuthConfig(
            mode="firebase",
            firebase_project_id="fake",
            bootstrap_emails=frozenset({"admin@example.com"}),
        )
        registry, _, auth_admin = _make_registry(cfg=cfg)
        user = _make_fb_user(email="stranger@example.com")

        with pytest.raises(PendingApprovalError):
            registry.ensure(user)
        auth_admin.update_user.assert_called_once()

    def test_no_bootstrap_disables_everyone(self):
        registry, _, auth_admin = _make_registry()
        user = _make_fb_user(email="anyone@example.com")

        with pytest.raises(PendingApprovalError):
            registry.ensure(user)
        auth_admin.update_user.assert_called_once()


# ---------------------------------------------------------------------------
# Repeat sign-ins (already-approved users must NOT be re-disabled)
# ---------------------------------------------------------------------------


class TestRepeatSignIn:
    def test_existing_firestore_doc_skips_disable(self):
        # Pre-seed Firestore so the registry thinks the user has signed
        # in before (possibly already approved by the admin).
        fs = FakeFirestore()
        fs.collection("users").document("u-1").set(
            {
                "uid": "u-1",
                "email": "u@example.com",
                "signInCount": 3,
                "createdAt": "2026-01-01T00:00:00+00:00",
                "lastSeenAt": "2026-04-01T00:00:00+00:00",
            }
        )

        registry, _, auth_admin = _make_registry(firestore=fs)
        user = _make_fb_user()

        # No raise — already known user.
        registry.ensure(user)
        auth_admin.update_user.assert_not_called()

        # Counter bumped.
        doc = fs.collection("users").document("u-1").to_dict()
        assert doc["signInCount"] == 4

    def test_process_cache_skips_refetch(self):
        registry, fs, auth_admin = _make_registry()
        user = _make_fb_user()

        # First call raises and disables.
        with pytest.raises(PendingApprovalError):
            registry.ensure(user)
        assert auth_admin.update_user.call_count == 1

        # Second call within the same process: the in-memory seen-set
        # short-circuits to the bump path. No second disable call.
        # (In production this happens when the admin enables the user
        # and they hit /auth/me again — we must NOT re-disable them.)
        auth_admin.update_user.reset_mock()
        registry.ensure(user)
        auth_admin.update_user.assert_not_called()


# ---------------------------------------------------------------------------
# Defensive behaviour
# ---------------------------------------------------------------------------


class TestDefensive:
    def test_firestore_failure_does_not_block(self):
        """If Firestore is unreachable, don't lock a legitimate user out."""
        registry, _, auth_admin = _make_registry()
        # Force the Firestore stub to blow up.
        broken = MagicMock()
        broken.collection.side_effect = RuntimeError("firestore offline")
        registry._firestore = broken

        user = _make_fb_user()
        # Must not raise.
        registry.ensure(user)
        auth_admin.update_user.assert_not_called()

    def test_disable_failure_does_not_block(self):
        """If the disable call fails, let the user in rather than 500."""
        registry, _, auth_admin = _make_registry()
        auth_admin.update_user.side_effect = RuntimeError("admin SDK unhappy")
        user = _make_fb_user()

        # Still swallows — pending_approval is not raised because we
        # couldn't enforce the disable, so letting them in is safer
        # than 500-ing the request.
        registry.ensure(user)
