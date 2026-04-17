"""Tests for the /auth/drive/* endpoints.

Exercises the full Drive OAuth flow against mocked Google endpoints so
the suite runs offline. No ``[gdrive]`` or real Firebase admin needed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lci_mini.auth.config import DriveOAuthConfig
from lci_mini.auth.drive import (
    STATE_COOKIE_NAME,
    generate_state,
    reset_token_store_for_tests,
    sign_state_payload,
)
from lci_mini.auth.endpoints import build_drive_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_client_secrets(dir: Path) -> Path:
    p = dir / "client_secret.json"
    p.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "cid-123.apps.googleusercontent.com",
                    "client_secret": "cs-xyz",
                    "redirect_uris": ["http://testserver/auth/drive/callback"],
                }
            }
        )
    )
    return p


def _install_fake_firestore() -> None:
    """Patch sys.modules so FirestoreTokenStore doesn't need firebase-admin.

    Tests that DON'T set OPENBENCH_AUTH_DISABLED will reach the
    FirestoreTokenStore code path. Satisfy its firebase-admin lazy
    import with a fake that records in a dict.
    """
    if "firebase_admin" in sys.modules:
        return
    fake_fb = types.ModuleType("firebase_admin")
    fake_fs = types.ModuleType("firebase_admin.firestore")

    _store: dict[str, dict[str, Any]] = {}

    def _collection(_name: str) -> Any:
        col = MagicMock()

        def _document(uid: str) -> Any:
            doc = MagicMock()
            doc.set.side_effect = lambda payload: _store.__setitem__(uid, dict(payload))

            def _get() -> Any:
                snap = MagicMock()
                if uid in _store:
                    snap.exists = True
                    snap.to_dict.return_value = _store[uid]
                else:
                    snap.exists = False
                return snap

            doc.get.side_effect = _get
            doc.delete.side_effect = lambda: _store.pop(uid, None)
            return doc

        col.document.side_effect = _document
        return col

    client = MagicMock()
    client.collection.side_effect = _collection
    fake_fs.client = MagicMock(return_value=client)  # type: ignore[attr-defined]
    fake_fb.firestore = fake_fs  # type: ignore[attr-defined]
    sys.modules["firebase_admin"] = fake_fb
    sys.modules["firebase_admin.firestore"] = fake_fs


def _patch_drive_service(folder_id: str = "new-folder-id") -> Any:
    """Return a MagicMock Drive service that always find-or-creates ``folder_id``."""
    service = MagicMock()

    def _list(**_: Any) -> Any:
        resp = MagicMock()
        # First call returns "not found" — triggers create path.
        resp.execute.return_value = {"files": []}
        return resp

    def _create(**_: Any) -> Any:
        resp = MagicMock()
        resp.execute.return_value = {"id": folder_id}
        return resp

    service.files.return_value.list.side_effect = _list
    service.files.return_value.create.side_effect = _create
    return service


def _fake_token_exchange_response(
    access_token: str = "at-1",
    refresh_token: str | None = "rt-1",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "access_token": access_token,
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/drive.file",
        "token_type": "Bearer",
    }
    if refresh_token is not None:
        payload["refresh_token"] = refresh_token
    return payload


class _FakeUrlopenResp:
    def __init__(self, payload: dict[str, Any]):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures — one app per test, clean env
# ---------------------------------------------------------------------------


@pytest.fixture
def drive_app(tmp_path, monkeypatch):
    # Identity: dev bypass
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)

    # Drive OAuth config
    cs = _write_client_secrets(tmp_path)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", str(cs))
    monkeypatch.setenv("DRIVE_OAUTH_REDIRECT_URL", "http://testserver/auth/drive/callback")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-change-me")

    reset_token_store_for_tests()

    app = FastAPI()
    app.include_router(build_drive_router(redirect_home="/"))
    yield app
    reset_token_store_for_tests()


@pytest.fixture
def client(drive_app):
    return TestClient(drive_app)


# ---------------------------------------------------------------------------
# /auth/drive/connect
# ---------------------------------------------------------------------------


class TestConnect:
    def test_connect_returns_authorize_url(self, client):
        resp = client.post("/auth/drive/connect")
        assert resp.status_code == 200
        data = resp.json()
        assert "authorizeUrl" in data
        assert "accounts.google.com" in data["authorizeUrl"]
        assert "access_type=offline" in data["authorizeUrl"]
        assert "prompt=consent" in data["authorizeUrl"]

    def test_connect_sets_signed_state_cookie(self, client):
        resp = client.post("/auth/drive/connect")
        assert STATE_COOKIE_NAME in resp.cookies
        # Cookie is opaque — just verify it's non-empty and parseable.
        cookie_val = resp.cookies[STATE_COOKIE_NAME]
        assert len(cookie_val) > 10

    def test_connect_disabled_when_oauth_unconfigured(self, monkeypatch, tmp_path):
        reset_token_store_for_tests()
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRETS", raising=False)
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        app = FastAPI()
        app.include_router(build_drive_router())
        resp = TestClient(app).post("/auth/drive/connect")
        assert resp.status_code == 501
        assert "GOOGLE_OAUTH_CLIENT_SECRETS" in resp.json()["detail"]

    def test_connect_uses_user_email_as_login_hint(self, client):
        # In dev-disabled mode the synthetic user has email=None, so
        # the URL should NOT include login_hint. This verifies we
        # don't accidentally send "login_hint=".
        resp = client.post("/auth/drive/connect")
        assert "login_hint=" not in resp.json()["authorizeUrl"]


# ---------------------------------------------------------------------------
# /auth/drive/callback
# ---------------------------------------------------------------------------


class TestCallback:
    def test_callback_without_state_cookie_returns_400(self, client):
        resp = client.get("/auth/drive/callback?code=abc&state=xyz")
        assert resp.status_code == 400
        assert "state cookie" in resp.json()["detail"].lower()

    def test_callback_state_mismatch_returns_400(self, drive_app, client):
        cfg = DriveOAuthConfig.from_env()
        cookie = sign_state_payload(cfg, {"uid": "dev", "state": "server-state"})
        client.cookies.set(STATE_COOKIE_NAME, cookie)
        resp = client.get(
            "/auth/drive/callback?code=abc&state=attacker-state",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "CSRF state mismatch" in resp.json()["detail"]

    def test_callback_error_param_returns_400(self, client):
        resp = client.get("/auth/drive/callback?error=access_denied")
        assert resp.status_code == 400
        assert "access_denied" in resp.json()["detail"]

    def test_callback_missing_code_returns_400(self, drive_app, client):
        cfg = DriveOAuthConfig.from_env()
        state = generate_state()
        cookie = sign_state_payload(cfg, {"uid": "dev", "state": state})
        client.cookies.set(STATE_COOKIE_NAME, cookie)
        resp = client.get(f"/auth/drive/callback?state={state}")
        assert resp.status_code == 400

    def test_callback_happy_path_persists_token_and_redirects(self, drive_app, client):
        cfg = DriveOAuthConfig.from_env()
        state = generate_state()
        cookie = sign_state_payload(cfg, {"uid": "dev", "state": state})
        client.cookies.set(STATE_COOKIE_NAME, cookie)

        with (
            patch(
                "urllib.request.urlopen",
                return_value=_FakeUrlopenResp(_fake_token_exchange_response()),
            ),
            patch(
                "lci_mini.auth.drive._build_drive_service_with_token",
                return_value=_patch_drive_service(folder_id="folder-new"),
            ),
        ):
            resp = client.get(
                f"/auth/drive/callback?code=auth-code&state={state}",
                follow_redirects=False,
            )

        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

        # Token persisted
        from lci_mini.auth.drive import get_token_store

        stored = get_token_store().load("dev")
        assert stored is not None
        assert stored.refresh_token == "rt-1"
        assert stored.openbench_folder_id == "folder-new"
        assert stored.scopes == ("https://www.googleapis.com/auth/drive.file",)

    def test_callback_rejects_response_without_refresh_token(self, drive_app, client):
        cfg = DriveOAuthConfig.from_env()
        state = generate_state()
        cookie = sign_state_payload(cfg, {"uid": "dev", "state": state})
        client.cookies.set(STATE_COOKIE_NAME, cookie)

        with patch(
            "urllib.request.urlopen",
            return_value=_FakeUrlopenResp(_fake_token_exchange_response(refresh_token=None)),
        ):
            resp = client.get(
                f"/auth/drive/callback?code=abc&state={state}",
                follow_redirects=False,
            )
        assert resp.status_code == 400
        assert "refresh_token" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /auth/drive/disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_noop_when_not_connected(self, client):
        resp = client.post("/auth/drive/disconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["disconnected"] is False

    def test_disconnect_revokes_and_deletes(self, drive_app, client):
        # Seed a token
        from lci_mini.auth.drive import get_token_store

        from openbench.integrations.firebase_auth import DriveToken

        store = get_token_store()
        store.save(
            DriveToken(
                uid="dev",
                refresh_token="rt-live",
                client_id="cid",
                client_secret="cs",
            )
        )

        with patch(
            "openbench.integrations.firebase_auth.revoke_refresh_token", return_value=True
        ) as revoke:
            resp = client.post("/auth/drive/disconnect")

        assert resp.status_code == 200
        assert resp.json()["disconnected"] is True
        revoke.assert_called_once_with("rt-live")
        assert store.load("dev") is None

    def test_disconnect_swallows_revoke_failures(self, drive_app, client):
        from lci_mini.auth.drive import get_token_store

        from openbench.integrations.firebase_auth import DriveToken

        store = get_token_store()
        store.save(
            DriveToken(
                uid="dev",
                refresh_token="rt-live",
                client_id="cid",
                client_secret="cs",
            )
        )

        with patch(
            "openbench.integrations.firebase_auth.revoke_refresh_token",
            side_effect=RuntimeError("network fell over"),
        ):
            resp = client.post("/auth/drive/disconnect")
        # Still succeeds; token still removed locally
        assert resp.status_code == 200
        assert store.load("dev") is None


# ---------------------------------------------------------------------------
# /auth/drive/status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_not_connected(self, client):
        resp = client.get("/auth/drive/status")
        assert resp.status_code == 200
        assert resp.json() == {"connected": False}

    def test_status_connected(self, drive_app, client):
        from lci_mini.auth.drive import get_token_store

        from openbench.integrations.firebase_auth import DriveToken

        store = get_token_store()
        store.save(
            DriveToken(
                uid="dev",
                refresh_token="rt",
                client_id="c",
                client_secret="s",
                connected_email="jane@example.com",
                openbench_folder_id="folder-1",
                scopes=("https://www.googleapis.com/auth/drive.file",),
            )
        )
        resp = client.get("/auth/drive/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["email"] == "jane@example.com"
        assert data["folderId"] == "folder-1"


# ---------------------------------------------------------------------------
# DriveOAuthConfig.from_env
# ---------------------------------------------------------------------------


class TestDriveOAuthConfig(unittest.TestCase):
    def setUp(self):
        for k in (
            "GOOGLE_OAUTH_CLIENT_SECRETS",
            "DRIVE_OAUTH_REDIRECT_URL",
            "DRIVE_OAUTH_SCOPES",
            "SESSION_SECRET",
        ):
            os.environ.pop(k, None)

    def test_disabled_without_client_secrets(self):
        cfg = DriveOAuthConfig.from_env()
        self.assertFalse(cfg.enabled)

    def test_requires_redirect_url_when_client_secrets_set(self):
        with tempfile.TemporaryDirectory() as d:
            _write_client_secrets(Path(d))
            os.environ["GOOGLE_OAUTH_CLIENT_SECRETS"] = str(Path(d) / "client_secret.json")
            with self.assertRaises(RuntimeError) as ctx:
                DriveOAuthConfig.from_env()
            self.assertIn("DRIVE_OAUTH_REDIRECT_URL", str(ctx.exception))

    def test_requires_session_secret(self):
        with tempfile.TemporaryDirectory() as d:
            _write_client_secrets(Path(d))
            os.environ["GOOGLE_OAUTH_CLIENT_SECRETS"] = str(Path(d) / "client_secret.json")
            os.environ["DRIVE_OAUTH_REDIRECT_URL"] = "https://x/cb"
            with self.assertRaises(RuntimeError) as ctx:
                DriveOAuthConfig.from_env()
            self.assertIn("SESSION_SECRET", str(ctx.exception))

    def test_enabled_with_all_required(self):
        with tempfile.TemporaryDirectory() as d:
            _write_client_secrets(Path(d))
            os.environ["GOOGLE_OAUTH_CLIENT_SECRETS"] = str(Path(d) / "client_secret.json")
            os.environ["DRIVE_OAUTH_REDIRECT_URL"] = "https://x/cb"
            os.environ["SESSION_SECRET"] = "secret"
            cfg = DriveOAuthConfig.from_env()
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.redirect_url, "https://x/cb")
            self.assertEqual(cfg.scopes, ("https://www.googleapis.com/auth/drive.file",))

    def test_custom_scopes_from_env(self):
        with tempfile.TemporaryDirectory() as d:
            _write_client_secrets(Path(d))
            os.environ["GOOGLE_OAUTH_CLIENT_SECRETS"] = str(Path(d) / "client_secret.json")
            os.environ["DRIVE_OAUTH_REDIRECT_URL"] = "https://x/cb"
            os.environ["SESSION_SECRET"] = "secret"
            os.environ["DRIVE_OAUTH_SCOPES"] = (
                "https://www.googleapis.com/auth/drive,"
                "https://www.googleapis.com/auth/userinfo.email"
            )
            try:
                cfg = DriveOAuthConfig.from_env()
                self.assertEqual(len(cfg.scopes), 2)
            finally:
                os.environ.pop("DRIVE_OAUTH_SCOPES", None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
