"""Local auth tests for Dashboard Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

import pytest

DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "examples" / "dashboard-chat" / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))


pytestmark = pytest.mark.integration


class _EnvBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(
            environ,
            {
                "DASHBOARD_CHAT_AUTH_SECRET": "test-secret",
                "DASHBOARD_CHAT_STORAGE_ROOT": self._tmp.name,
            },
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestCredentials(_EnvBase):
    def test_default_admin_credentials(self):
        from dashboard_chat.auth import verify_credentials

        account = verify_credentials("admin", "admin123")
        self.assertIsNotNone(account)
        self.assertEqual(account.role, "admin")

    def test_default_guest_credentials(self):
        from dashboard_chat.auth import verify_credentials

        account = verify_credentials("guest", "guest123")
        self.assertIsNotNone(account)
        self.assertEqual(account.role, "guest")

    def test_username_is_case_insensitive(self):
        from dashboard_chat.auth import verify_credentials

        self.assertIsNotNone(verify_credentials("Admin", "admin123"))

    def test_wrong_password_rejected(self):
        from dashboard_chat.auth import verify_credentials

        self.assertIsNone(verify_credentials("admin", "wrong"))
        self.assertIsNone(verify_credentials("admin", ""))

    def test_unknown_user_rejected(self):
        from dashboard_chat.auth import verify_credentials

        self.assertIsNone(verify_credentials("root", "admin123"))

    def test_env_password_override(self):
        from dashboard_chat.auth import verify_credentials

        with patch.dict(environ, {"DASHBOARD_CHAT_ADMIN_PASSWORD": "s3cret"}, clear=False):
            self.assertIsNone(verify_credentials("admin", "admin123"))
            self.assertIsNotNone(verify_credentials("admin", "s3cret"))


class TestTokens(_EnvBase):
    def _admin(self):
        from dashboard_chat.auth import verify_credentials

        return verify_credentials("admin", "admin123")

    def test_token_round_trip(self):
        from dashboard_chat.auth import issue_token, verify_token

        token = issue_token(self._admin())
        account = verify_token(token)
        self.assertIsNotNone(account)
        self.assertEqual(account.username, "admin")
        self.assertEqual(account.role, "admin")

    def test_expired_token_rejected(self):
        from dashboard_chat.auth import issue_token, verify_token

        token = issue_token(self._admin(), ttl_seconds=-1)
        self.assertIsNone(verify_token(token))

    def test_tampered_token_rejected(self):
        from dashboard_chat.auth import issue_token, verify_token

        token = issue_token(self._admin())
        username, expiry, signature = token.split(".")
        self.assertIsNone(verify_token(f"guest.{expiry}.{signature}"))
        self.assertIsNone(verify_token(f"{username}.{expiry}.AAAA{signature[4:]}"))
        self.assertIsNone(verify_token("garbage"))

    def test_removed_user_token_revoked(self):
        from dashboard_chat.auth import issue_token, verify_token
        from dashboard_chat.users import get_user_store

        store = get_user_store()
        store.add("temp", "hunter22", "guest")
        from dashboard_chat.auth import verify_credentials

        token = issue_token(verify_credentials("temp", "hunter22"))
        self.assertIsNotNone(verify_token(token))
        store.remove("temp")
        self.assertIsNone(verify_token(token))

    def test_resolve_bearer(self):
        from dashboard_chat.auth import issue_token, resolve_bearer

        token = issue_token(self._admin())
        self.assertIsNotNone(resolve_bearer(f"Bearer {token}"))
        self.assertIsNone(resolve_bearer(token))
        self.assertIsNone(resolve_bearer(""))


if __name__ == "__main__":
    unittest.main()
