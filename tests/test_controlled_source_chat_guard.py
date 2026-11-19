"""Role-guard and owner-scoping tests for the Controlled Source Chat wrapper."""

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

REPO_ROOT = Path(__file__).resolve().parents[1]
for example in ("general-chat", "controlled-source-chat"):
    src = REPO_ROOT / "examples" / example / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


pytestmark = pytest.mark.integration


class ControlledSourceChatTestCase(unittest.TestCase):
    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(self.tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(self.tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(self.tmpdir / "downloads"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                    "CONTROLLED_CHAT_AUTH_SECRET": "test-secret",
                    "GENERAL_CHAT_SHARED_SOURCES_OWNER": "admin",
                    "GENERAL_CHAT_SHARED_SOURCES_THREAD": "controlled-sources",
                },
                clear=False,
            )
        )
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from controlled_source_chat.app import build_app

        return TestClient(build_app())

    def _login(self, client: TestClient, username: str, password: str) -> dict[str, str]:
        response = client.post(
            "/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}


class TestAuthEndpoints(ControlledSourceChatTestCase):
    def test_login_returns_role_and_token(self):
        client = self._client()
        body = client.post(
            "/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()
        self.assertEqual(body["role"], "admin")
        self.assertTrue(body["token"])

    def test_bad_password_is_401(self):
        client = self._client()
        response = client.post(
            "/auth/login", json={"username": "admin", "password": "nope"}
        )
        self.assertEqual(response.status_code, 401)

    def test_me_reflects_token(self):
        client = self._client()
        headers = self._login(client, "guest", "guest123")
        body = client.get("/auth/me", headers=headers).json()
        self.assertEqual(body, {"username": "guest", "role": "guest"})

    def test_me_without_token_is_401(self):
        client = self._client()
        self.assertEqual(client.get("/auth/me").status_code, 401)


class TestRoleGuard(ControlledSourceChatTestCase):
    def test_protected_paths_require_token(self):
        client = self._client()
        for path in ("/sessions", "/chat/sources/controlled-sources", "/mcp/tools"):
            response = client.get(path)
            self.assertEqual(response.status_code, 401, path)

    def test_health_is_open(self):
        client = self._client()
        self.assertEqual(client.get("/health").status_code, 200)

    def test_guest_blocked_from_management_endpoints(self):
        client = self._client()
        guest = self._login(client, "guest", "guest123")
        blocked = [
            ("POST", "/chat/upload"),
            ("POST", "/chat/uploads/initiate"),
            ("POST", "/chat/attachments/upload"),
            ("GET", "/chat/sources/controlled-sources"),
            ("POST", "/chat/sources/controlled-sources/text"),
            ("DELETE", "/chat/sources/controlled-sources"),
            ("GET", "/chat/sources/discover"),
            ("GET", "/mcp/tools"),
            ("GET", "/mcp/catalogs"),
            ("GET", "/toolhive/status"),
            ("GET", "/functions"),
            ("POST", "/dashboard/publish"),
            ("GET", "/persona"),
            ("GET", "/skills"),
        ]
        for method, path in blocked:
            response = client.request(method, path, headers=guest)
            self.assertEqual(response.status_code, 403, f"{method} {path}")

    def test_guest_allowed_chat_surface(self):
        client = self._client()
        guest = self._login(client, "guest", "guest123")
        self.assertEqual(client.get("/sessions", headers=guest).status_code, 200)
        self.assertEqual(client.get("/chat/actions", headers=guest).status_code, 200)
        self.assertEqual(client.get("/controlled/sources", headers=guest).status_code, 200)

    def test_admin_can_manage_sources(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        created = client.post(
            "/chat/sources/controlled-sources/text",
            headers=admin,
            json={"name": "kb-note", "text": "The Zylor Bridge opened in 1987."},
        )
        self.assertEqual(created.status_code, 200)
        listed = client.get("/chat/sources/controlled-sources", headers=admin).json()
        self.assertEqual([s["name"] for s in listed], ["kb-note"])
        self.assertEqual(listed[0]["owner"], "admin")

    def test_controlled_sources_exposes_admin_curation_to_guests(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        guest = self._login(client, "guest", "guest123")
        client.post(
            "/chat/sources/controlled-sources/text",
            headers=admin,
            json={"name": "kb-note", "text": "The Zylor Bridge opened in 1987."},
        )

        listed = client.get("/controlled/sources", headers=guest).json()

        self.assertEqual([s["name"] for s in listed], ["kb-note"])
        self.assertIn("Zylor Bridge", listed[0]["textPreview"])
        self.assertNotIn("text", listed[0])

    def test_sessions_are_scoped_per_role_account(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        guest = self._login(client, "guest", "guest123")

        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        store = SQLiteSessionStore(
            str(self.tmpdir / "storage" / "sessions.db"), owner="admin"
        )
        store.save(ChatSession(session_id="admin-session", title="Admin test"))

        as_admin = client.get("/sessions", headers=admin).json()
        as_guest = client.get("/sessions", headers=guest).json()

        self.assertEqual([s["sessionId"] for s in as_admin], ["admin-session"])
        self.assertEqual(as_guest, [])


class TestGuestIsNotAdmin(ControlledSourceChatTestCase):
    """General Chat runs with its own auth off under this wrapper.

    It used to treat every request the wrapper let through as an admin, so
    the guest account could use ``/admin/*``. The wrapper now stamps the
    role and General Chat honors it.
    """

    _ADMIN_ROUTES = (
        ("GET", "/admin/users"),
        ("GET", "/admin/capabilities"),
        ("GET", "/admin/runtime-settings"),
        ("POST", "/admin/users"),
        ("PUT", "/admin/capabilities"),
    )

    def test_guest_is_denied_every_admin_route(self):
        client = self._client()
        guest = self._login(client, "guest", "guest123")
        for method, path in self._ADMIN_ROUTES:
            response = client.request(method, path, headers=guest, json={})
            self.assertEqual(response.status_code, 403, f"{method} {path}")

    def test_guest_cannot_promote_itself_with_the_local_role_header(self):
        client = self._client()
        guest = {**self._login(client, "guest", "guest123"), "X-Local-Role": "admin"}
        for method, path in self._ADMIN_ROUTES:
            response = client.request(method, path, headers=guest, json={})
            self.assertEqual(response.status_code, 403, f"{method} {path}")

    def test_guest_is_reported_as_a_plain_user(self):
        client = self._client()
        guest = self._login(client, "guest", "guest123")
        me = client.get("/account/me", headers=guest)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json().get("role"), "user")

    def test_admin_keeps_admin_routes(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        self.assertEqual(client.get("/admin/capabilities", headers=admin).status_code, 200)
        me = client.get("/account/me", headers=admin)
        self.assertEqual(me.json().get("role"), "admin")

    def test_local_role_header_does_not_override_a_stamped_role(self):
        # The header is only a local-dev aid; it never raises a stamped role.
        client = self._client()
        admin = {**self._login(client, "admin", "admin123"), "X-Local-Role": "user"}
        self.assertEqual(client.get("/admin/capabilities", headers=admin).status_code, 200)


class TestDeployedPasswordPosture(ControlledSourceChatTestCase):
    """The published demo passwords must not work on a deployment."""

    _POSTURE_VARS = (
        "K_SERVICE",
        "GENERAL_CHAT_STATIC_DIR",
        "CONTROLLED_CHAT_ADMIN_PASSWORD",
        "CONTROLLED_CHAT_GUEST_PASSWORD",
        "CONTROLLED_CHAT_ALLOW_DEFAULT_PASSWORDS",
    )

    def _posture_env(self, **values: str) -> None:
        """Set exactly ``values`` among the posture variables for this test.

        Registered with addCleanup *before* any client is built, so it is
        undone after the client's own environment patch (cleanups run in
        reverse order) and nothing leaks into later tests.
        """
        patcher = patch.dict(environ, values, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in self._POSTURE_VARS:
            if name not in values:
                environ.pop(name, None)

    def test_deployed_image_without_admin_password_refuses_to_start(self):
        self._posture_env(K_SERVICE="controlled-source-chat")
        with self.assertRaisesRegex(RuntimeError, "CONTROLLED_CHAT_ADMIN_PASSWORD"):
            self._client()

    def test_deployed_image_rejects_the_demo_default_even_when_set(self):
        self._posture_env(
            K_SERVICE="controlled-source-chat", CONTROLLED_CHAT_ADMIN_PASSWORD="admin123"
        )
        with self.assertRaises(RuntimeError):
            self._client()

    def test_deployed_image_with_real_passwords(self):
        self._posture_env(
            K_SERVICE="controlled-source-chat", CONTROLLED_CHAT_ADMIN_PASSWORD="Str0ng-One"
        )
        client = self._client()
        for username, password in (
            ("admin", "admin123"),
            ("guest", "guest123"),
            ("guest", ""),
        ):
            response = client.post("/auth/login", json={"username": username, "password": password})
            self.assertEqual(response.status_code, 401, f"{username}/{password!r}")
        ok = client.post("/auth/login", json={"username": "admin", "password": "Str0ng-One"})
        self.assertEqual(ok.status_code, 200)

    def test_static_dir_also_marks_a_deployment(self):
        from controlled_source_chat import auth

        self._posture_env(GENERAL_CHAT_STATIC_DIR="/app/dist")
        with self.assertRaises(RuntimeError):
            auth.assert_password_posture()

    def test_explicit_opt_in_keeps_the_demo_passwords(self):
        from controlled_source_chat import auth

        self._posture_env(K_SERVICE="x", CONTROLLED_CHAT_ALLOW_DEFAULT_PASSWORDS="1")
        auth.assert_password_posture()
        self.assertEqual(auth._password_for("admin"), "admin123")
        self.assertEqual(auth._password_for("guest"), "guest123")

    def test_local_runs_keep_the_demo_passwords(self):
        from controlled_source_chat import auth

        self._posture_env()
        auth.assert_password_posture()
        self.assertEqual(auth._password_for("admin"), "admin123")

    def test_posture_variables_do_not_leak_between_tests(self):
        # Guards the ordering the helper relies on.
        before = {name: environ.get(name) for name in self._POSTURE_VARS}
        case = type(self)("test_deployed_image_with_real_passwords")
        result = unittest.TestResult()
        case.run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        self.assertEqual({name: environ.get(name) for name in self._POSTURE_VARS}, before)


if __name__ == "__main__":
    unittest.main()
