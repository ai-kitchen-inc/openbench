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
    def test_verify_without_extras_raises_install_hint(self):
        v = FirebaseIDVerifier(project_id="demo", service_account_file="/x")
        # Pretend firebase_admin is not installed: clear any cached
        # fake installation and block the import.
        _remove_fake_firebase_admin()
        with patch.dict("sys.modules", {"firebase_admin": None}):
            with self.assertRaises(ImportError) as ctx:
                v.verify("fake-token")
            self.assertIn("pip install openbench[firebase]", str(ctx.exception))


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
        user = self.verifier.verify("a.b.c")
        self.assertIsInstance(user, FirebaseUser)
        self.assertEqual(user.uid, "u-42")
        self.assertEqual(user.email, "jane@example.com")
        self.assertEqual(user.name, "Jane Doe")
        self.assertTrue(user.email_verified)

    def test_verify_exposes_raw_claims(self):
        user = self.verifier.verify("a.b.c")
        self.assertEqual(user.raw_claims["iss"], "https://securetoken.google.com/demo")

    def test_verify_passes_check_revoked_through(self):
        self.verifier.verify("tok", check_revoked=False)
        call_kwargs = self.auth.verify_id_token.call_args.kwargs
        self.assertIs(call_kwargs["check_revoked"], False)

    def test_verify_uses_sub_claim_when_uid_missing(self):
        self.auth.verify_id_token.return_value = {"sub": "sub-user", "email": None}
        user = self.verifier.verify("tok")
        self.assertEqual(user.uid, "sub-user")

    def test_empty_uid_when_neither_uid_nor_sub_present(self):
        self.auth.verify_id_token.return_value = {"email": "x@y.z"}
        user = self.verifier.verify("tok")
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
            self.verifier.verify("tok")

    def test_revoked_token(self):
        self.auth.verify_id_token.side_effect = self.auth.RevokedIdTokenError("revoked")
        with self.assertRaises(TokenRevokedError):
            self.verifier.verify("tok")

    def test_wrong_project_surfaces_as_wrong_project_error(self):
        """Firebase reports wrong-project as InvalidIdTokenError with 'audience' in the message."""
        self.auth.verify_id_token.side_effect = self.auth.InvalidIdTokenError(
            "The audience does not match"
        )
        with self.assertRaises(WrongProjectError):
            self.verifier.verify("tok")

    def test_generic_invalid_token(self):
        self.auth.verify_id_token.side_effect = self.auth.InvalidIdTokenError("bogus signature")
        with self.assertRaises(InvalidTokenError) as ctx:
            self.verifier.verify("tok")
        # Must be the base class, not one of the specific subclasses
        self.assertNotIsInstance(ctx.exception, TokenExpiredError)
        self.assertNotIsInstance(ctx.exception, TokenRevokedError)
        self.assertNotIsInstance(ctx.exception, WrongProjectError)

    def test_value_error_from_google_auth_layer_maps_to_invalid(self):
        """Malformed non-JWT strings raise ValueError in google-auth; we re-wrap."""
        self.auth.verify_id_token.side_effect = ValueError("malformed token")
        with self.assertRaises(InvalidTokenError):
            self.verifier.verify("not-a-jwt")


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
        verifier.verify("tok-1")
        verifier.verify("tok-2")
        verifier.verify("tok-3")
        self.assertEqual(firebase_admin.initialize_app.call_count, 1)

    def test_reuses_app_when_already_initialized(self):
        """If a host app has already called initialize_app with our name, we fall back to get_app()."""
        import firebase_admin

        firebase_admin.initialize_app.side_effect = ValueError("app already exists")
        verifier = FirebaseIDVerifier(project_id="demo", service_account_file="/x")
        # Should not raise
        verifier.verify("tok")
        firebase_admin.get_app.assert_called_once()


if __name__ == "__main__":
    unittest.main()
