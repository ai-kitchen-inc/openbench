"""Tests for :class:`FirebaseIDVerifier`.

The Firebase Admin SDK is mocked at the module level so tests run
without ``[firebase]`` extras installed. One test verifies the lazy-
import helpful-error path.
"""

from __future__ import annotations

import sys
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.integrations.firebase_auth import (
    FirebaseIDVerifier,
    FirebaseUser,
    InvalidTokenError,
    TokenExpiredError,
    TokenRevokedError,
    WrongProjectError,
)


def _install_fake_firebase_admin(
    *,
    claims: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Install a fake ``firebase_admin`` module tree in ``sys.modules``.

    Returns the ``auth`` submodule mock so tests can assert its
    ``verify_id_token`` was called with the expected args.
    """
    fake_fb = types.ModuleType("firebase_admin")
    fake_credentials = types.ModuleType("firebase_admin.credentials")
    fake_auth = types.ModuleType("firebase_admin.auth")

    # Error classes — match Firebase's class names so the verifier's
    # isinstance checks work.
    class _ExpiredIdTokenError(Exception): ...

    class _RevokedIdTokenError(Exception): ...

    class _InvalidIdTokenError(Exception): ...

    fake_auth.ExpiredIdTokenError = _ExpiredIdTokenError  # type: ignore[attr-defined]
    fake_auth.RevokedIdTokenError = _RevokedIdTokenError  # type: ignore[attr-defined]
    fake_auth.InvalidIdTokenError = _InvalidIdTokenError  # type: ignore[attr-defined]

    verify = MagicMock()
    if raise_exc is not None:
        verify.side_effect = raise_exc
    else:
        verify.return_value = claims or {
            "uid": "user-1",
            "email": "jane@example.com",
            "name": "Jane",
            "email_verified": True,
        }
    fake_auth.verify_id_token = verify  # type: ignore[attr-defined]

    # Minimal Certificate factory
    fake_credentials.Certificate = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

    # Minimal app lifecycle
    fake_fb.initialize_app = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_fb.get_app = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_fb.credentials = fake_credentials  # type: ignore[attr-defined]
    fake_fb.auth = fake_auth  # type: ignore[attr-defined]

    sys.modules["firebase_admin"] = fake_fb
    sys.modules["firebase_admin.credentials"] = fake_credentials
    sys.modules["firebase_admin.auth"] = fake_auth
    return fake_auth  # type: ignore[return-value]


def _remove_fake_firebase_admin() -> None:
    for name in [
        "firebase_admin",
        "firebase_admin.credentials",
        "firebase_admin.auth",
    ]:
        sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_requires_project_id(self):
        with self.assertRaises(ValueError):
            FirebaseIDVerifier(project_id="")

    def test_accepts_service_account_file(self):
        v = FirebaseIDVerifier(project_id="demo", service_account_file="/x")
        self.assertEqual(v.project_id, "demo")

    def test_accepts_explicit_credentials(self):
        v = FirebaseIDVerifier(project_id="demo", credentials=object())
        self.assertEqual(v.project_id, "demo")

    def test_construction_is_offline(self):
        """Building a verifier must not import firebase_admin or hit the network."""
        FirebaseIDVerifier(project_id="demo", service_account_file="/x")

    def test_repr_contains_project_id(self):
        v = FirebaseIDVerifier(project_id="abc-123", service_account_file="/x")
        self.assertIn("abc-123", repr(v))


# ---------------------------------------------------------------------------
# Missing dependency error
# ---------------------------------------------------------------------------


class TestMissingDependency(unittest.TestCase):
    def test_verify_with_check_revoked_without_extras_raises_install_hint(self):
        """Only the check_revoked=True path requires firebase-admin."""
        v = FirebaseIDVerifier(project_id="demo", service_account_file="/x")
        _remove_fake_firebase_admin()
        with patch.dict("sys.modules", {"firebase_admin": None}):
            with self.assertRaises(ImportError) as ctx:
                v.verify("fake-token", check_revoked=True)
            self.assertIn("firebase-admin", str(ctx.exception))


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestVerifyHappyPath(unittest.TestCase):
    def setUp(self):
        self.auth = _install_fake_firebase_admin(
            claims={
                "uid": "u-42",
                "email": "jane@example.com",
                "name": "Jane Doe",
                "email_verified": True,
                "iss": "https://securetoken.google.com/demo",
            }
        )
        self.verifier = FirebaseIDVerifier(project_id="demo", service_account_file="/x")

    def tearDown(self):
        _remove_fake_firebase_admin()

    def test_verify_returns_firebase_user(self):
        user = self.verifier.verify("a.b.c", check_revoked=True)
        self.assertIsInstance(user, FirebaseUser)
        self.assertEqual(user.uid, "u-42")
        self.assertEqual(user.email, "jane@example.com")
        self.assertEqual(user.name, "Jane Doe")
        self.assertTrue(user.email_verified)

    def test_verify_exposes_raw_claims(self):
        user = self.verifier.verify("a.b.c", check_revoked=True)
        self.assertEqual(user.raw_claims["iss"], "https://securetoken.google.com/demo")

    def test_check_revoked_true_routes_to_admin_sdk(self):
        self.verifier.verify("tok", check_revoked=True)
        call_kwargs = self.auth.verify_id_token.call_args.kwargs
        # The Admin SDK path always passes check_revoked=True — the
        # kwarg on verify() selects the path, not a pass-through.
        self.assertIs(call_kwargs["check_revoked"], True)

    def test_check_revoked_false_bypasses_admin_sdk(self):
        """Default (check_revoked=False) must not call firebase_admin at all."""
        import google.oauth2.id_token as gid

        with patch.object(gid, "verify_firebase_token", return_value={"uid": "u"}) as mocked:
            self.verifier.verify("tok")
        # Admin SDK mock not touched; google-auth called instead.
        self.assertEqual(self.auth.verify_id_token.call_count, 0)
        self.assertEqual(mocked.call_count, 1)

    def test_verify_uses_sub_claim_when_uid_missing(self):
        self.auth.verify_id_token.return_value = {"sub": "sub-user", "email": None}
        user = self.verifier.verify("tok", check_revoked=True)
        self.assertEqual(user.uid, "sub-user")

    def test_empty_uid_when_neither_uid_nor_sub_present(self):
        self.auth.verify_id_token.return_value = {"email": "x@y.z"}
        user = self.verifier.verify("tok", check_revoked=True)
        self.assertEqual(user.uid, "")


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestVerifyErrors(unittest.TestCase):
    def setUp(self):
        self.auth = _install_fake_firebase_admin()
        self.verifier = FirebaseIDVerifier(project_id="demo", service_account_file="/x")

    def tearDown(self):
        _remove_fake_firebase_admin()

    def test_empty_token_raises_invalid(self):
        with self.assertRaises(InvalidTokenError):
            self.verifier.verify("")

    def test_expired_token(self):
        self.auth.verify_id_token.side_effect = self.auth.ExpiredIdTokenError("token expired")
        with self.assertRaises(TokenExpiredError):
            self.verifier.verify("tok", check_revoked=True)

    def test_revoked_token(self):
        self.auth.verify_id_token.side_effect = self.auth.RevokedIdTokenError("revoked")
        with self.assertRaises(TokenRevokedError):
            self.verifier.verify("tok", check_revoked=True)

    def test_wrong_project_surfaces_as_wrong_project_error(self):
        """Firebase reports wrong-project as InvalidIdTokenError with 'audience' in the message."""
        self.auth.verify_id_token.side_effect = self.auth.InvalidIdTokenError(
            "The audience does not match"
        )
        with self.assertRaises(WrongProjectError):
            self.verifier.verify("tok", check_revoked=True)

    def test_generic_invalid_token(self):
        self.auth.verify_id_token.side_effect = self.auth.InvalidIdTokenError("bogus signature")
        with self.assertRaises(InvalidTokenError) as ctx:
            self.verifier.verify("tok", check_revoked=True)
        # Must be the base class, not one of the specific subclasses
        self.assertNotIsInstance(ctx.exception, TokenExpiredError)
        self.assertNotIsInstance(ctx.exception, TokenRevokedError)
        self.assertNotIsInstance(ctx.exception, WrongProjectError)

    def test_value_error_from_google_auth_layer_maps_to_invalid(self):
        """Malformed non-JWT strings raise ValueError in google-auth; we re-wrap."""
        self.auth.verify_id_token.side_effect = ValueError("malformed token")
        with self.assertRaises(InvalidTokenError):
            self.verifier.verify("not-a-jwt", check_revoked=True)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


class TestAppLifecycle(unittest.TestCase):
    def setUp(self):
        self.auth = _install_fake_firebase_admin()

    def tearDown(self):
        _remove_fake_firebase_admin()

    def test_app_is_built_once(self):
        import firebase_admin

        verifier = FirebaseIDVerifier(project_id="demo", service_account_file="/x")
        verifier.verify("tok-1", check_revoked=True)
        verifier.verify("tok-2", check_revoked=True)
        verifier.verify("tok-3", check_revoked=True)
        self.assertEqual(firebase_admin.initialize_app.call_count, 1)

    def test_reuses_app_when_already_initialized(self):
        """If a host app has already called initialize_app with our name, we fall back to get_app()."""
        import firebase_admin

        firebase_admin.initialize_app.side_effect = ValueError("app already exists")
        verifier = FirebaseIDVerifier(project_id="demo", service_account_file="/x")
        # Should not raise
        verifier.verify("tok", check_revoked=True)
        firebase_admin.get_app.assert_called_once()


# ---------------------------------------------------------------------------
# google-auth lightweight path (default when check_revoked=False)
# ---------------------------------------------------------------------------


class TestGoogleAuthVerifyPath(unittest.TestCase):
    """The default path uses google.oauth2.id_token — no credentials needed."""

    def setUp(self):
        # No firebase_admin fake — this path must not touch it.
        _remove_fake_firebase_admin()

    def _verify_with_mock(self, *, return_value=None, side_effect=None):
        import google.oauth2.id_token as gid

        v = FirebaseIDVerifier(project_id="demo")
        with patch.object(gid, "verify_firebase_token") as mocked:
            if side_effect is not None:
                mocked.side_effect = side_effect
            else:
                mocked.return_value = return_value
            return v.verify("a.b.c"), mocked

    def test_returns_firebase_user_on_success(self):
        user, mocked = self._verify_with_mock(
            return_value={"uid": "u-1", "email": "j@e.z", "email_verified": True},
        )
        self.assertEqual(user.uid, "u-1")
        self.assertEqual(user.email, "j@e.z")
        self.assertTrue(user.email_verified)
        # Was called with the right audience (our project_id).
        self.assertEqual(mocked.call_args.kwargs["audience"], "demo")

    def test_expired_token_raises_typed_exception(self):
        with self.assertRaises(TokenExpiredError):
            self._verify_with_mock(side_effect=ValueError("Token expired"))

    def test_wrong_audience_raises_typed_exception(self):
        with self.assertRaises(WrongProjectError):
            self._verify_with_mock(side_effect=ValueError("Invalid audience"))

    def test_generic_invalid_value_error_maps_to_invalid(self):
        with self.assertRaises(InvalidTokenError):
            self._verify_with_mock(side_effect=ValueError("bad signature"))

    def test_empty_token_raises_invalid_without_network(self):
        v = FirebaseIDVerifier(project_id="demo")
        with self.assertRaises(InvalidTokenError):
            v.verify("")


if __name__ == "__main__":
    unittest.main()
