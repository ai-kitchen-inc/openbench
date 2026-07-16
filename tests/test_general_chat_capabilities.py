"""Tests for role-scoped capability flags and admin route gating."""

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

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.capabilities import (  # noqa: E402
    blocked_flag_for,
    default_capabilities,
    resolve_capabilities,
)

pytestmark = pytest.mark.integration

ADMIN = FirebaseUser(uid="uid-admin", email="boss@example.com")
MEMBER = FirebaseUser(uid="uid-member", email="member@example.com")

ADMIN_H = {"Authorization": "Bearer token-admin"}
MEMBER_H = {"Authorization": "Bearer token-member"}


class TestCapabilityResolution(unittest.TestCase):
    def test_defaults(self):
        caps = default_capabilities()
        self.assertTrue(caps["roles"]["user"]["attachments"])
        self.assertFalse(caps["roles"]["user"]["mcp_management"])
        self.assertFalse(caps["roles"]["user"]["custom_functions"])
        self.assertTrue(caps["global"]["file_generation"])

    def test_resolve_merges_partial_and_drops_unknown(self):
        stored = {
            "roles": {"user": {"attachments": False, "made_up_flag": True}},
            "global": {"file_generation": False, "nope": True},
        }
        caps = resolve_capabilities(stored)
        self.assertFalse(caps["roles"]["user"]["attachments"])
        self.assertNotIn("made_up_flag", caps["roles"]["user"])
        self.assertFalse(caps["global"]["file_generation"])
        self.assertNotIn("nope", caps["global"])
        # untouched flags fall back to defaults
        self.assertTrue(caps["roles"]["user"]["session_sources"])

    def test_resolve_garbage_returns_defaults(self):
        self.assertEqual(resolve_capabilities("junk"), default_capabilities())
        self.assertEqual(resolve_capabilities(None), default_capabilities())

    def test_blocked_flag_for(self):
        self.assertEqual(blocked_flag_for("/chat/upload"), "attachments")
        self.assertEqual(blocked_flag_for("/chat/uploads/initiate"), "attachments")
        self.assertEqual(blocked_flag_for("/chat/sources/s1/text"), "session_sources")
        self.assertEqual(blocked_flag_for("/mcp/catalogs"), "mcp_management")
        self.assertEqual(blocked_flag_for("/toolhive/workloads"), "mcp_management")
        self.assertEqual(blocked_flag_for("/functions"), "custom_functions")
        self.assertEqual(blocked_flag_for("/dashboard/publish"), "dashboards")
        self.assertEqual(blocked_flag_for("/image-search/previews/x.png"), "image_search")
        self.assertIsNone(blocked_flag_for("/awp"))
        self.assertIsNone(blocked_flag_for("/sessions"))
        self.assertIsNone(blocked_flag_for("/persona"))


class TestCapabilityGatingEndToEnd(unittest.TestCase):
    def _client(self) -> TestClient:
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
                    "GENERAL_CHAT_BOOTSTRAP_ADMIN": "boss@example.com",
                    "GENERAL_CHAT_ALLOWED_EMAILS": "member@example.com",
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

        tokens = {
            "token-admin": ADMIN,
            "token-member": MEMBER,
            "token-ghost": FirebaseUser(uid="uid-ghost", email="ghost@example.com"),
        }
        verifier = Mock()
        verifier.verify.side_effect = lambda token, **_kw: tokens[token]
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    def test_account_me_reports_role_and_capabilities(self):
        client = self._client()
        admin_me = client.get("/account/me", headers=ADMIN_H).json()
        member_me = client.get("/account/me", headers=MEMBER_H).json()

        self.assertEqual(admin_me["role"], "admin")
        self.assertTrue(all(admin_me["capabilities"].values()))
        self.assertEqual(member_me["role"], "user")
        self.assertFalse(member_me["capabilities"]["mcp_management"])
        self.assertTrue(member_me["capabilities"]["attachments"])

    def test_admin_routes_blocked_for_user_role(self):
        client = self._client()
        self.assertEqual(client.get("/admin/users", headers=MEMBER_H).status_code, 403)
        self.assertEqual(client.get("/admin/users", headers=ADMIN_H).status_code, 200)

    def test_default_disabled_capability_blocks_user_but_not_admin(self):
        client = self._client()
        # mcp_management defaults off for users
        self.assertEqual(client.get("/mcp/tools", headers=MEMBER_H).status_code, 403)
        self.assertEqual(client.get("/mcp/tools", headers=ADMIN_H).status_code, 200)

    def test_admin_can_toggle_capability_live(self):
        client = self._client()
        # attachments default on → /chat/sources listing allowed
        self.assertEqual(
            client.get("/chat/sources/s1", headers=MEMBER_H).status_code, 200
        )
        response = client.put(
            "/admin/capabilities",
            headers=ADMIN_H,
            json={"roles": {"user": {"session_sources": False}}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["roles"]["user"]["session_sources"])

        blocked = client.get("/chat/sources/s1", headers=MEMBER_H)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["capability"], "session_sources")
        # admins bypass the toggle
        self.assertEqual(client.get("/chat/sources/s1", headers=ADMIN_H).status_code, 200)

    def test_capabilities_put_requires_admin(self):
        client = self._client()
        response = client.put(
            "/admin/capabilities",
            headers=MEMBER_H,
            json={"roles": {"user": {"attachments": False}}},
        )
        self.assertEqual(response.status_code, 403)

    def test_unknown_account_is_403(self):
        client = self._client()
        response = client.get(
            "/account/me", headers={"Authorization": "Bearer token-ghost"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("not allowed", response.json()["detail"])

    def test_auth_disabled_grants_admin(self):
        with patch.dict(environ, {"OPENBENCH_AUTH_DISABLED": "1"}, clear=False):
            client = self._client_disabled()
            me = client.get("/account/me").json()
        self.assertEqual(me["role"], "admin")
        self.assertEqual(me["email"], "local")

    def _client_disabled(self) -> TestClient:
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
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())


if __name__ == "__main__":
    unittest.main()
