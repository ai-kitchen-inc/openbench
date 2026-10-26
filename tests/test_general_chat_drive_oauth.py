"""Tests for General Chat per-user Drive OAuth endpoints."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.drive_auth import DriveOAuthManager  # noqa: E402
from openbench.integrations.firebase_auth import FileTokenStore  # noqa: E402
from openbench.integrations.firebase_auth.drive_oauth import TokenResponse  # noqa: E402

_ENV_VARS = (
    "GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS",
    "GENERAL_CHAT_DRIVE_OAUTH_REDIRECT_URL",
    "GENERAL_CHAT_SESSION_SECRET",
    "GENERAL_CHAT_DRIVE_TOKEN_ENCRYPTION_KEY",
    "GENERAL_CHAT_DRIVE_OAUTH_SCOPES",
    "GENERAL_CHAT_FIREBASE_PROJECT_ID",
)


class _DriveOAuthTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage_root = self._tmp.name
        self._saved_env = {name: os.environ.get(name) for name in _ENV_VARS}
        for name in _ENV_VARS:
            os.environ.pop(name, None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for name, value in self._saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _configure(self):
        secrets_path = Path(self.storage_root) / "client_secrets.json"
        secrets_path.write_text(
            json.dumps(
                {
                    "web": {
                        "client_id": "test-client-id",
                        "client_secret": "test-client-secret",
                        "redirect_uris": ["http://localhost:5174/auth/drive/callback"],
                    }
                }
            ),
            encoding="utf-8",
        )
        os.environ["GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS"] = str(secrets_path)
        os.environ["GENERAL_CHAT_DRIVE_OAUTH_REDIRECT_URL"] = (
            "http://localhost:5174/auth/drive/callback"
        )
        os.environ["GENERAL_CHAT_SESSION_SECRET"] = "unit-test-session-secret"
        os.environ["GENERAL_CHAT_DRIVE_TOKEN_ENCRYPTION_KEY"] = (
            base64.urlsafe_b64encode(b"0" * 32).decode()
        )

    def _client(self) -> tuple[TestClient, DriveOAuthManager]:
        manager = DriveOAuthManager(self.storage_root)
        app = FastAPI()
        app.include_router(manager.build_router())
        return TestClient(app), manager


class TestUnconfigured(_DriveOAuthTestBase):
    def test_status_reports_unconfigured(self):
        client, _ = self._client()
        response = client.get("/auth/drive/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"configured": False, "connected": False, "email": None}
        )

    def test_connect_returns_503(self):
        client, _ = self._client()
        self.assertEqual(client.post("/auth/drive/connect").status_code, 503)

    def test_incomplete_config_fails_fast(self):
        secrets_path = Path(self.storage_root) / "client_secrets.json"
        secrets_path.write_text("{}", encoding="utf-8")
        os.environ["GENERAL_CHAT_GOOGLE_OAUTH_CLIENT_SECRETS"] = str(secrets_path)
        with self.assertRaises(RuntimeError):
            DriveOAuthManager(self.storage_root)


class TestConnect(_DriveOAuthTestBase):
    def setUp(self):
        super().setUp()
        self._configure()

    def test_connect_returns_authorize_url_and_cookie(self):
        client, _ = self._client()
        response = client.post("/auth/drive/connect")
        self.assertEqual(response.status_code, 200)
        url = response.json()["authorizeUrl"]
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertIn("test-client-id", url)
        self.assertIn("drive.readonly", url)
        self.assertIn("__session", response.cookies)


class TestCallback(_DriveOAuthTestBase):
    def setUp(self):
        super().setUp()
        self._configure()

    def _start_connect(self, client: TestClient) -> str:
        """POST /connect and return the state param Google would echo back."""
        response = client.post("/auth/drive/connect")
        self.assertEqual(response.status_code, 200)
        query = parse_qs(urlparse(response.json()["authorizeUrl"]).query)
        return query["state"][0]

    def test_happy_path_persists_encrypted_token(self):
        client, manager = self._client()
        state = self._start_connect(client)
        token = TokenResponse(
            access_token="at-123",
            refresh_token="rt-456",
            expires_at=9999999999.0,
            scope="https://www.googleapis.com/auth/drive.readonly",
        )
        with (
            patch(
                "openbench.integrations.firebase_auth.exchange_code",
                return_value=token,
            ),
            patch.object(
                DriveOAuthManager,
                "_fetch_account_email",
                return_value="user@example.com",
            ),
        ):
            response = client.get(
                f"/auth/drive/callback?code=auth-code&state={state}",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("drive=connected", response.headers["location"])

        saved = manager._token_store().load("local")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.refresh_token, "rt-456")
        self.assertEqual(saved.connected_email, "user@example.com")

        # At-rest content must not contain the raw refresh token.
        token_dir = Path(self.storage_root) / "drive_tokens"
        raw = "".join(p.read_text(encoding="utf-8") for p in token_dir.glob("*.json"))
        self.assertNotIn("rt-456", raw)

        status = client.get("/auth/drive/status").json()
        self.assertTrue(status["connected"])
        self.assertEqual(status["email"], "user@example.com")

    def test_csrf_state_mismatch_rejected(self):
        client, _ = self._client()
        self._start_connect(client)
        response = client.get(
            "/auth/drive/callback?code=auth-code&state=wrong-state",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_cookie_rejected(self):
        client, _ = self._client()
        response = client.get(
            "/auth/drive/callback?code=auth-code&state=whatever",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_refresh_token_rejected(self):
        client, _ = self._client()
        state = self._start_connect(client)
        token = TokenResponse(
            access_token="at-123",
            refresh_token=None,
            expires_at=9999999999.0,
            scope="",
        )
        with patch(
            "openbench.integrations.firebase_auth.exchange_code", return_value=token
        ):
            response = client.get(
                f"/auth/drive/callback?code=auth-code&state={state}",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 400)

    def test_google_error_param_rejected(self):
        client, _ = self._client()
        response = client.get(
            "/auth/drive/callback?error=access_denied", follow_redirects=False
        )
        self.assertEqual(response.status_code, 400)


class TestDisconnect(_DriveOAuthTestBase):
    def setUp(self):
        super().setUp()
        self._configure()

    def test_disconnect_removes_token(self):
        client, manager = self._client()
        response = client.post("/auth/drive/connect")
        query = parse_qs(urlparse(response.json()["authorizeUrl"]).query)
        state = query["state"][0]
        token = TokenResponse(
            access_token="at",
            refresh_token="rt",
            expires_at=9999999999.0,
            scope="",
        )
        with (
            patch(
                "openbench.integrations.firebase_auth.exchange_code",
                return_value=token,
            ),
            patch.object(
                DriveOAuthManager, "_fetch_account_email", return_value=None
            ),
        ):
            client.get(
                f"/auth/drive/callback?code=c&state={state}", follow_redirects=False
            )
        self.assertIsNotNone(manager._token_store().load("local"))

        with patch(
            "openbench.integrations.firebase_auth.revoke_refresh_token",
            return_value=True,
        ) as mock_revoke:
            response = client.post("/auth/drive/disconnect")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["disconnected"])
        mock_revoke.assert_called_once_with("rt")
        self.assertIsNone(manager._token_store().load("local"))

    def test_disconnect_when_not_connected(self):
        client, _ = self._client()
        response = client.post("/auth/drive/disconnect")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["disconnected"])


class TestFileTokenStoreRoundTrip(_DriveOAuthTestBase):
    def test_credentials_for_none_without_token(self):
        self._configure()
        manager = DriveOAuthManager(self.storage_root)
        self.assertIsNone(manager.credentials_for("local"))
        self.assertIsInstance(manager._token_store(), FileTokenStore)


if __name__ == "__main__":
    unittest.main()
