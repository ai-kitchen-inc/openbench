"""Tests for the General Chat admin user/settings stores and seeding."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.admin_store import (  # noqa: E402
    DuplicateUserError,
    JsonSettingsStore,
    JsonUserStore,
    UnknownUserError,
    seed_users,
)


class TestJsonUserStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonUserStore(tmp.name)

    def test_add_and_get_normalizes_email(self):
        record = self.store.add("Admin@Example.COM", "admin", display_name=" Boss ")
        self.assertEqual(record.email, "admin@example.com")
        self.assertEqual(record.role, "admin")
        self.assertEqual(record.display_name, "Boss")
        self.assertEqual(self.store.get("ADMIN@example.com").email, "admin@example.com")

    def test_add_duplicate_raises(self):
        self.store.add("a@example.com")
        with self.assertRaises(DuplicateUserError):
            self.store.add("A@example.com")

    def test_add_invalid_email_or_role_raises(self):
        with self.assertRaises(ValueError):
            self.store.add("not-an-email")
        with self.assertRaises(ValueError):
            self.store.add("a@example.com", "superuser")

    def test_update_role_and_display_name(self):
        self.store.add("a@example.com", "user")
        record = self.store.update("a@example.com", role="admin", display_name="Alice")
        self.assertEqual(record.role, "admin")
        self.assertEqual(record.display_name, "Alice")

    def test_update_unknown_raises(self):
        with self.assertRaises(UnknownUserError):
            self.store.update("ghost@example.com", role="admin")

    def test_remove(self):
        self.store.add("a@example.com")
        self.assertTrue(self.store.remove("a@example.com"))
        self.assertFalse(self.store.remove("a@example.com"))
        self.assertIsNone(self.store.get("a@example.com"))

    def test_count_admins(self):
        self.store.add("a@example.com", "admin")
        self.store.add("b@example.com", "user")
        self.store.add("c@example.com", "admin")
        self.assertEqual(self.store.count_admins(), 2)

    def test_list_users_sorted_and_persisted(self):
        self.store.add("b@example.com")
        self.store.add("a@example.com")
        emails = [record.email for record in self.store.list_users()]
        self.assertEqual(emails, ["a@example.com", "b@example.com"])


class TestJsonSettingsStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonSettingsStore(tmp.name)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get("capabilities"))

    def test_set_get_roundtrip(self):
        value = {"roles": {"user": {"attachments": False}}}
        self.store.set("capabilities", value, updated_by="admin@example.com")
        self.assertEqual(self.store.get("capabilities"), value)

    def test_delete(self):
        self.store.set("persona", {"soul": "x"})
        self.assertTrue(self.store.delete("persona"))
        self.assertFalse(self.store.delete("persona"))
        self.assertIsNone(self.store.get("persona"))


class TestSeedUsers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonUserStore(tmp.name)

    def test_seeds_bootstrap_admin_and_allowlist_users(self):
        with patch.dict(
            environ,
            {
                "GENERAL_CHAT_BOOTSTRAP_ADMIN": "boss@example.com",
                "GENERAL_CHAT_ALLOWED_EMAILS": "boss@example.com, member@example.com",
            },
            clear=False,
        ):
            seeded = seed_users(self.store)
        self.assertEqual(seeded, 2)
        self.assertEqual(self.store.get("boss@example.com").role, "admin")
        self.assertEqual(self.store.get("member@example.com").role, "user")

    def test_seed_is_idempotent(self):
        with patch.dict(
            environ,
            {"GENERAL_CHAT_BOOTSTRAP_ADMIN": "boss@example.com"},
            clear=False,
        ):
            self.assertEqual(seed_users(self.store), 1)
            self.assertEqual(seed_users(self.store), 0)

    def test_seed_never_touches_populated_store(self):
        self.store.add("existing@example.com", "admin")
        with patch.dict(
            environ,
            {"GENERAL_CHAT_BOOTSTRAP_ADMIN": "boss@example.com"},
            clear=False,
        ):
            self.assertEqual(seed_users(self.store), 0)
        self.assertIsNone(self.store.get("boss@example.com"))


if __name__ == "__main__":
    unittest.main()
