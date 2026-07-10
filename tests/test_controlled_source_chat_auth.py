"""Local two-account auth tests for Controlled Source Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

import pytest

CONTROLLED_SRC = (
    Path(__file__).resolve().parents[1] / "examples" / "controlled-source-chat" / "src"
)
if str(CONTROLLED_SRC) not in sys.path:
    sys.path.insert(0, str(CONTROLLED_SRC))


pytestmark = pytest.mark.integration


class TestCredentials(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            environ, {"CONTROLLED_CHAT_AUTH_SECRET": "test-secret"}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_admin_credentials(self):
        from controlled_source_chat.auth import verify_credentials

        account = verify_credentials("admin", "admin123")
        self.assertIsNotNone(account)
        self.assertEqual(account.role, "admin")

    def test_default_guest_credentials(self):
        from controlled_source_chat.auth import verify_credentials

        account = verify_credentials("guest", "guest123")
        self.assertIsNotNone(account)
        self.assertEqual(account.role, "guest")

    def test_username_is_case_insensitive(self):
        from controlled_source_chat.auth import verify_credentials

        self.assertIsNotNone(verify_credentials("Admin", "admin123"))

    def test_wrong_password_rejected(self):
        from controlled_source_chat.auth import verify_credentials

        self.assertIsNone(verify_credentials("admin", "wrong"))
        self.assertIsNone(verify_credentials("admin", ""))

    def test_unknown_user_rejected(self):
        from controlled_source_chat.auth import verify_credentials

        self.assertIsNone(verify_credentials("root", "admin123"))

    def test_env_password_override(self):
        from controlled_source_chat.auth import verify_credentials

        with patch.dict(environ, {"CONTROLLED_CHAT_ADMIN_PASSWORD": "s3cret"}, clear=False):
            self.assertIsNone(verify_credentials("admin", "admin123"))
            self.assertIsNotNone(verify_credentials("admin", "s3cret"))


class TestTokens(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            environ, {"CONTROLLED_CHAT_AUTH_SECRET": "test-secret"}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _account(self):
        from controlled_source_chat.auth import verify_credentials

        return verify_credentials("guest", "guest123")

    def test_round_trip(self):
        from controlled_source_chat.auth import issue_token, verify_token

        token = issue_token(self._account())
        account = verify_token(token)
        self.assertIsNotNone(account)
        self.assertEqual((account.username, account.role), ("guest", "guest"))

    def test_expired_token_rejected(self):
        from controlled_source_chat.auth import issue_token, verify_token

        token = issue_token(self._account(), ttl_seconds=-1)
        self.assertIsNone(verify_token(token))

    def test_tampered_token_rejected(self):
        from controlled_source_chat.auth import issue_token, verify_token

        token = issue_token(self._account())
        username, expiry, signature = token.split(".")
        self.assertIsNone(verify_token(f"admin.{expiry}.{signature}"))
        self.assertIsNone(verify_token(f"{username}.9999999999.{signature}"))
        self.assertIsNone(verify_token("garbage"))
        self.assertIsNone(verify_token(""))

    def test_token_survives_process_restart_semantics(self):
        # Same secret -> a token minted "before restart" still verifies.
        from controlled_source_chat.auth import issue_token, verify_token

        token = issue_token(self._account())
        self.assertIsNotNone(verify_token(token))

    def test_bearer_resolution(self):
        from controlled_source_chat.auth import issue_token, resolve_bearer

        token = issue_token(self._account())
        self.assertIsNotNone(resolve_bearer(f"Bearer {token}"))
        self.assertIsNone(resolve_bearer(token))
        self.assertIsNone(resolve_bearer("Basic abc"))
        self.assertIsNone(resolve_bearer(""))

    def test_generated_secret_is_persisted(self):
        import controlled_source_chat.auth as auth_module

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                environ,
                {"GENERAL_CHAT_STORAGE_ROOT": tmp, "CONTROLLED_CHAT_AUTH_SECRET": ""},
                clear=False,
            ):
                first = auth_module._auth_secret()
                second = auth_module._auth_secret()
                self.assertEqual(first, second)
                self.assertTrue((Path(tmp) / "controlled-auth-secret.txt").is_file())


if __name__ == "__main__":
    unittest.main()
