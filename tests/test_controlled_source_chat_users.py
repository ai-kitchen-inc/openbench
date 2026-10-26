"""User store and admin user-management endpoint tests for Controlled Source Chat."""

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


class TestPasswordHashing(unittest.TestCase):
    def test_round_trip(self):
        from controlled_source_chat.users import hash_password, verify_password

        stored = hash_password("s3cret-pw")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("s3cret-pw", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_hashes_are_salted(self):
        from controlled_source_chat.users import hash_password

        self.assertNotEqual(hash_password("same"), hash_password("same"))

    def test_malformed_stored_hash_rejected(self):
        from controlled_source_chat.users import verify_password

        self.assertFalse(verify_password("anything", ""))
        self.assertFalse(verify_password("anything", "plaintext"))
        self.assertFalse(verify_password("anything", "md5$1$x$y"))


class TestUserStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "controlled-users.json"

    def _store(self):
        from controlled_source_chat.users import UserStore

        return UserStore(self.path)

    def test_builtins_seeded_without_writing_file(self):
        store = self._store()
        usernames = {record.username for record in store.list_users()}
        self.assertEqual(usernames, {"admin", "guest"})
        self.assertTrue(all(record.builtin for record in store.list_users()))
        self.assertFalse(self.path.exists())

    def test_add_persists_across_instances(self):
        store = self._store()
        record = store.add("alice", "password1", "guest")
        self.assertFalse(record.builtin)
        self.assertIsNotNone(record.created_at)

        reloaded = self._store().get("alice")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.role, "guest")
        self.assertIsNotNone(reloaded.password_hash)

    def test_add_validation(self):
        from controlled_source_chat.users import DuplicateUserError

        store = self._store()
        with self.assertRaises(ValueError):
            store.add("Bad Name!", "password1", "guest")
        with self.assertRaises(ValueError):
            store.add("alice", "short", "guest")
        with self.assertRaises(ValueError):
            store.add("alice", "password1", "root")
        with self.assertRaises(DuplicateUserError):
            store.add("admin", "password1", "guest")
        store.add("alice", "password1", "guest")
        with self.assertRaises(DuplicateUserError):
            store.add("ALICE", "password1", "guest")

    def test_remove_rules(self):
        from controlled_source_chat.users import BuiltinUserError, UnknownUserError

        store = self._store()
        with self.assertRaises(BuiltinUserError):
            store.remove("admin")
        with self.assertRaises(BuiltinUserError):
            store.remove("guest")
        with self.assertRaises(UnknownUserError):
            store.remove("nobody")
        store.add("alice", "password1", "guest")
        store.remove("alice")
        self.assertIsNone(store.get("alice"))

    def test_existing_file_not_overwritten_by_seeding(self):
        store = self._store()
        store.add("alice", "password1", "guest")
        before = self.path.read_text(encoding="utf-8")
        self._store().list_users()
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_public_dict_hides_hash(self):
        store = self._store()
        record = store.add("alice", "password1", "guest")
        public = record.to_public_dict()
        self.assertEqual(set(public), {"username", "role", "builtin", "createdAt"})


class UsersEndpointTestCase(unittest.TestCase):
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


class TestUsersEndpoints(UsersEndpointTestCase):
    def test_requires_token(self):
        client = self._client()
        self.assertEqual(client.get("/controlled/users").status_code, 401)

    def test_guest_is_forbidden(self):
        client = self._client()
        guest = self._login(client, "guest", "guest123")
        self.assertEqual(client.get("/controlled/users", headers=guest).status_code, 403)
        self.assertEqual(
            client.post(
                "/controlled/users",
                headers=guest,
                json={"username": "eve", "password": "password1", "role": "admin"},
            ).status_code,
            403,
        )
        self.assertEqual(
            client.delete("/controlled/users/guest", headers=guest).status_code, 403
        )

    def test_admin_lists_builtins(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        listed = client.get("/controlled/users", headers=admin).json()
        self.assertEqual(
            {(u["username"], u["role"], u["builtin"]) for u in listed},
            {("admin", "admin", True), ("guest", "guest", True)},
        )
        self.assertTrue(all("passwordHash" not in u for u in listed))

    def test_add_user_then_login(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        created = client.post(
            "/controlled/users",
            headers=admin,
            json={"username": "Alice", "password": "password1", "role": "guest"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["username"], "alice")

        body = client.post(
            "/auth/login", json={"username": "alice", "password": "password1"}
        ).json()
        self.assertEqual(body["role"], "guest")

    def test_add_duplicate_is_409(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        payload = {"username": "alice", "password": "password1", "role": "guest"}
        self.assertEqual(
            client.post("/controlled/users", headers=admin, json=payload).status_code, 201
        )
        self.assertEqual(
            client.post("/controlled/users", headers=admin, json=payload).status_code, 409
        )

    def test_add_invalid_is_400(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        for payload in (
            {"username": "Bad Name!", "password": "password1", "role": "guest"},
            {"username": "alice", "password": "short", "role": "guest"},
            {"username": "alice", "password": "password1", "role": "root"},
        ):
            response = client.post("/controlled/users", headers=admin, json=payload)
            self.assertEqual(response.status_code, 400, response.text)

    def test_delete_revokes_login_and_tokens(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        client.post(
            "/controlled/users",
            headers=admin,
            json={"username": "alice", "password": "password1", "role": "guest"},
        )
        alice = self._login(client, "alice", "password1")

        deleted = client.delete("/controlled/users/alice", headers=admin)
        self.assertEqual(deleted.status_code, 200)

        # Login fails and the old token is dead immediately.
        self.assertEqual(
            client.post(
                "/auth/login", json={"username": "alice", "password": "password1"}
            ).status_code,
            401,
        )
        self.assertEqual(client.get("/auth/me", headers=alice).status_code, 401)

    def test_delete_builtin_is_400(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        self.assertEqual(
            client.delete("/controlled/users/guest", headers=admin).status_code, 400
        )

    def test_delete_self_is_400(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        self.assertEqual(
            client.delete("/controlled/users/admin", headers=admin).status_code, 400
        )

    def test_delete_unknown_is_404(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        self.assertEqual(
            client.delete("/controlled/users/nobody", headers=admin).status_code, 404
        )

    def test_added_admin_can_manage_users(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        client.post(
            "/controlled/users",
            headers=admin,
            json={"username": "boss", "password": "password1", "role": "admin"},
        )
        boss = self._login(client, "boss", "password1")
        self.assertEqual(client.get("/controlled/users", headers=boss).status_code, 200)


if __name__ == "__main__":
    unittest.main()
