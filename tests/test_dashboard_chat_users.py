"""User store tests for Dashboard Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pytest

DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "examples" / "dashboard-chat" / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))


pytestmark = pytest.mark.integration


class TestUserStore(unittest.TestCase):
    def setUp(self):
        from dashboard_chat.users import UserStore

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = UserStore(Path(self._tmp.name) / "users.json")

    def test_builtins_present_without_file(self):
        names = {record.username for record in self.store.list_users()}
        self.assertEqual(names, {"admin", "guest"})

    def test_add_and_get(self):
        from dashboard_chat.users import verify_password

        record = self.store.add("alice", "wonder1", "guest")
        self.assertFalse(record.builtin)
        loaded = self.store.get("alice")
        self.assertIsNotNone(loaded)
        self.assertTrue(verify_password("wonder1", loaded.password_hash))
        self.assertFalse(verify_password("nope", loaded.password_hash))

    def test_duplicate_rejected(self):
        from dashboard_chat.users import DuplicateUserError

        self.store.add("alice", "wonder1", "guest")
        with self.assertRaises(DuplicateUserError):
            self.store.add("alice", "wonder2", "guest")

    def test_invalid_username_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add("Not Valid!", "wonder1", "guest")

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add("bob", "abc", "guest")

    def test_invalid_role_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add("bob", "wonder1", "root")

    def test_remove(self):
        from dashboard_chat.users import BuiltinUserError, UnknownUserError

        self.store.add("alice", "wonder1", "guest")
        self.store.remove("alice")
        self.assertIsNone(self.store.get("alice"))
        with self.assertRaises(UnknownUserError):
            self.store.remove("alice")
        with self.assertRaises(BuiltinUserError):
            self.store.remove("admin")

    def test_public_dict_hides_hash(self):
        record = self.store.add("alice", "wonder1", "guest")
        self.assertNotIn("passwordHash", record.to_public_dict())

    def test_persistence_across_instances(self):
        from dashboard_chat.users import UserStore

        self.store.add("alice", "wonder1", "admin")
        fresh = UserStore(Path(self._tmp.name) / "users.json")
        loaded = fresh.get("alice")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.role, "admin")


if __name__ == "__main__":
    unittest.main()
