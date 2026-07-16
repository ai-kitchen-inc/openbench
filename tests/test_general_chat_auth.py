"""Tests for General Chat Firebase auth enforcement."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from openbench.integrations.firebase_auth import FirebaseUser, InvalidTokenError

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))


pytestmark = pytest.mark.integration


class TestGeneralChatFirebaseAuth(unittest.TestCase):
    def _client(self, *, verify_result=None, verify_error: Exception | None = None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "GENERAL_CHAT_FIREBASE_PROJECT_ID": "demo-project",
                    "GENERAL_CHAT_ALLOWED_EMAILS": "allowed@example.com",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)

        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))

        verifier = Mock()
        if verify_error is not None:
            verifier.verify.side_effect = verify_error
        else:
            verifier.verify.return_value = verify_result or FirebaseUser(
                uid="user-1",
                email="allowed@example.com",
            )
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app()), verifier

    def test_health_is_public_when_auth_enabled(self):
        client, verifier = self._client()

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        verifier.verify.assert_not_called()

    def test_protected_route_requires_bearer_token(self):
        client, verifier = self._client()

        response = client.get("/persona")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Missing Bearer token", response.json()["detail"])
        verifier.verify.assert_not_called()

    def test_invalid_firebase_token_is_rejected(self):
        client, _verifier = self._client(verify_error=InvalidTokenError("bad token"))

        response = client.get("/persona", headers={"Authorization": "Bearer bad"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid Firebase ID token.")

    def test_non_allowlisted_user_is_rejected(self):
        client, _verifier = self._client(
            verify_result=FirebaseUser(uid="user-2", email="other@example.com")
        )

        response = client.get("/persona", headers={"Authorization": "Bearer valid"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("not allowed", response.json()["detail"])

    def test_allowlisted_user_can_access_protected_route(self):
        client, verifier = self._client()

        response = client.get("/persona", headers={"Authorization": "Bearer valid"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"loaded": False})
        verifier.verify.assert_called_once_with("valid", check_revoked=False)

    def test_api_schema_docs_are_disabled(self):
        client, _verifier = self._client()

        for path in ("/openapi.json", "/docs", "/redoc"):
            response = client.get(path)
            self.assertNotEqual(response.status_code, 200, f"{path} should not be served")

    def test_downloads_static_mount_is_public(self):
        """Generated-file download links are plain anchors (no Bearer header):
        /downloads must answer without auth — 404 for a missing file, never 401."""
        client, verifier = self._client()

        response = client.get("/downloads/not-found.xlsx")

        self.assertEqual(response.status_code, 404)
        verifier.verify.assert_not_called()

    def test_uploads_static_mount_is_protected(self):
        client, verifier = self._client()

        missing = client.get("/uploads/not-found.txt")
        allowed = client.get("/uploads/not-found.txt", headers={"Authorization": "Bearer valid"})

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(allowed.status_code, 404)
        verifier.verify.assert_called_once_with("valid", check_revoked=False)


if __name__ == "__main__":
    unittest.main()
