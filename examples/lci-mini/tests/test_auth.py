"""Tests for lci-mini's auth wiring (AuthConfig + verify_firebase_token).

Identity layer only (Milestone 1 of the auth RFC). No Drive OAuth yet.
"""

from __future__ import annotations

import sys
import types
import unittest
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lci_mini.auth.config import AuthConfig

# ---------------------------------------------------------------------------
# AuthConfig.from_env
# ---------------------------------------------------------------------------


class TestAuthConfig(unittest.TestCase):
    def test_empty_env_returns_none_mode(self):
        cfg = AuthConfig.from_env({})
        self.assertEqual(cfg.mode, "none")
        self.assertIsNone(cfg.firebase_project_id)

    def test_disabled_flag_returns_disabled_mode(self):
        for val in ("1", "true", "YES"):
            cfg = AuthConfig.from_env({"OPENBENCH_AUTH_DISABLED": val})
            self.assertEqual(cfg.mode, "disabled")

    def test_firebase_project_id_returns_firebase_mode(self):
        cfg = AuthConfig.from_env({"FIREBASE_PROJECT_ID": "demo-project"})
        self.assertEqual(cfg.mode, "firebase")
        self.assertEqual(cfg.firebase_project_id, "demo-project")
        self.assertIsNone(cfg.firebase_admin_credentials)

    def test_firebase_with_admin_credentials_path(self):
        cfg = AuthConfig.from_env(
            {
                "FIREBASE_PROJECT_ID": "demo",
                "FIREBASE_ADMIN_CREDENTIALS": "/secrets/fb.json",
            }
        )
        self.assertEqual(cfg.firebase_admin_credentials, "/secrets/fb.json")

    def test_disabled_and_firebase_together_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            AuthConfig.from_env(
                {
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "FIREBASE_PROJECT_ID": "demo",
                }
            )
        self.assertIn("cannot be combined", str(ctx.exception))


# ---------------------------------------------------------------------------
# Helpers: fake firebase_admin installation for verify_firebase_token tests
# ---------------------------------------------------------------------------


def _install_fake_firebase_admin(
    *,
    claims: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    fake_fb = types.ModuleType("firebase_admin")
    fake_credentials = types.ModuleType("firebase_admin.credentials")
    fake_auth = types.ModuleType("firebase_admin.auth")

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
            "uid": "u-1",
            "email": "u@example.com",
            "name": "User",
            "email_verified": True,
        }
    fake_auth.verify_id_token = verify  # type: ignore[attr-defined]

    fake_credentials.Certificate = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_fb.initialize_app = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_fb.get_app = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_fb.credentials = fake_credentials  # type: ignore[attr-defined]
    fake_fb.auth = fake_auth  # type: ignore[attr-defined]

    sys.modules["firebase_admin"] = fake_fb
    sys.modules["firebase_admin.credentials"] = fake_credentials
    sys.modules["firebase_admin.auth"] = fake_auth
    return fake_auth  # type: ignore[return-value]


def _remove_fake_firebase_admin() -> None:
    for name in ("firebase_admin", "firebase_admin.credentials", "firebase_admin.auth"):
        sys.modules.pop(name, None)


def _reset_verifier_singleton() -> None:
    """Clear the cached verifier between test cases."""
    import lci_mini.auth.dependencies as deps

    with deps._verifier_lock:
        deps._verifier_singleton = None
        deps._verifier_config_hash = None


def _build_app() -> FastAPI:
    from fastapi import Depends
    from lci_mini.auth import verify_firebase_token

    app = FastAPI()

    @app.get("/me")
    async def me(user=Depends(verify_firebase_token)) -> dict:
        return {
            "uid": user.uid,
            "email": user.email,
            "emailVerified": user.email_verified,
        }

    return app


# ---------------------------------------------------------------------------
# Disabled mode
# ---------------------------------------------------------------------------


class TestDisabledMode(unittest.TestCase):
    def setUp(self):
        _reset_verifier_singleton()

    def test_returns_synthetic_dev_user(self, monkeypatch=None):
        # unittest doesn't use pytest fixtures; patch env via os.environ directly
        import os

        for k in ("OPENBENCH_AUTH_DISABLED", "FIREBASE_PROJECT_ID"):
            os.environ.pop(k, None)
        os.environ["OPENBENCH_AUTH_DISABLED"] = "1"
        try:
            client = TestClient(_build_app())
            resp = client.get("/me")
            assert resp.status_code == 200
            data = resp.json()
            assert data["uid"] == "dev"
            assert data["email"] is None
        finally:
            os.environ.pop("OPENBENCH_AUTH_DISABLED", None)

    def test_disabled_mode_ignores_authorization_header(self):
        import os

        os.environ["OPENBENCH_AUTH_DISABLED"] = "1"
        try:
            client = TestClient(_build_app())
            resp = client.get("/me", headers={"Authorization": "Bearer whatever"})
            assert resp.status_code == 200
            assert resp.json()["uid"] == "dev"
        finally:
            os.environ.pop("OPENBENCH_AUTH_DISABLED", None)


# ---------------------------------------------------------------------------
# None (legacy) mode
# ---------------------------------------------------------------------------


class TestNoneMode(unittest.TestCase):
    def setUp(self):
        _reset_verifier_singleton()

    def test_returns_anonymous_user_without_any_env_flags(self):
        import os

        for k in ("OPENBENCH_AUTH_DISABLED", "FIREBASE_PROJECT_ID"):
            os.environ.pop(k, None)
        client = TestClient(_build_app())
        resp = client.get("/me")
        assert resp.status_code == 200
        assert resp.json()["uid"] == "anonymous"


# ---------------------------------------------------------------------------
# Firebase mode
# ---------------------------------------------------------------------------


class TestFirebaseMode:
    """pytest-style — we need fixtures for proper env isolation."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        """Patch the google-auth verify path — that's what
        ``verify_firebase_token`` hits by default (no credentials
        needed). The old Admin-SDK mock is still installed for the
        legacy ``check_revoked=True`` path, but the dependency
        doesn't use it.
        """
        import google.oauth2.id_token as gid

        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-project")
        _reset_verifier_singleton()
        _install_fake_firebase_admin()  # harmless; path not used by default
        self.verify_mock = MagicMock(
            return_value={
                "uid": "user-42",
                "email": "jane@example.com",
                "name": "Jane",
                "email_verified": True,
            }
        )
        monkeypatch.setattr(gid, "verify_firebase_token", self.verify_mock)
        yield
        _remove_fake_firebase_admin()
        _reset_verifier_singleton()

    def test_missing_authorization_header_returns_401(self):
        client = TestClient(_build_app())
        resp = client.get("/me")
        assert resp.status_code == 401
        assert "Missing Bearer token" in resp.json()["detail"]
        assert resp.headers.get("www-authenticate") == "Bearer"

    def test_malformed_authorization_header_returns_401(self):
        client = TestClient(_build_app())
        resp = client.get("/me", headers={"Authorization": "NotBearer foo"})
        assert resp.status_code == 401

    def test_valid_token_returns_firebase_user(self):
        client = TestClient(_build_app())
        resp = client.get("/me", headers={"Authorization": "Bearer valid.id.token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "user-42"
        assert data["email"] == "jane@example.com"
        assert data["emailVerified"] is True
        # Verifier saw the raw token (scheme stripped)
        self.verify_mock.assert_called_once()
        assert self.verify_mock.call_args.args[0] == "valid.id.token"

    def test_expired_token_returns_401(self):
        self.verify_mock.side_effect = ValueError("Token expired")
        client = TestClient(_build_app())
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_wrong_project_returns_401_with_specific_detail(self):
        self.verify_mock.side_effect = ValueError("Invalid audience")
        client = TestClient(_build_app())
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 401
        assert "different Firebase project" in resp.json()["detail"]

    def test_invalid_token_returns_401(self):
        self.verify_mock.side_effect = ValueError("bogus signature")
        client = TestClient(_build_app())
        resp = client.get("/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid ID token"


# ---------------------------------------------------------------------------
# /auth/me endpoint is mounted on lci-mini's real app
# ---------------------------------------------------------------------------


class TestAuthMeEndpointMounted:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        _reset_verifier_singleton()
        yield
        _reset_verifier_singleton()

    def test_auth_me_route_exists(self):
        from lci_mini.server.app import create_app

        app = create_app()
        routes = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/auth/me" in routes

    def test_auth_me_in_disabled_mode_returns_dev_user(self):
        from lci_mini.server.app import create_app

        client = TestClient(create_app())
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "dev"
        assert data["mode"] == "disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
