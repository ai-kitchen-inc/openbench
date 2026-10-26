"""Tests for SQLiteSessionStore."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from openbench.chat.session import ChatSession
from openbench.chat.session_store import SessionOwnershipError
from openbench.chat.stores.sqlite import SQLiteSessionStore


class TestSQLiteSessionStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "nested" / "sessions.db"
        self.store = SQLiteSessionStore(self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def _session(self, sid: str, title: str = "T", user_text: str = "hello") -> ChatSession:
        session = ChatSession(session_id=sid, title=title)
        session.add_user_message(user_text)
        session.add_assistant_message("hi back")
        return session

    def test_creates_parent_directory(self):
        self.assertTrue(self.db_path.parent.is_dir())

    def test_save_then_load_roundtrip(self):
        original = self._session("s1", title="Roundtrip")
        self.store.save(original)
        loaded = self.store.load("s1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_id, "s1")
        self.assertEqual(loaded.title, "Roundtrip")
        self.assertEqual(len(loaded.messages), 2)

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("nope"))

    def test_save_is_upsert(self):
        self.store.save(self._session("s1", title="First"))
        self.store.save(self._session("s1", title="Second"))
        loaded = self.store.load("s1")
        self.assertEqual(loaded.title, "Second")
        # Still a single row.
        self.assertEqual(len(self.store.list()), 1)

    def test_list_orders_newest_first_and_paginates(self):
        for i in range(3):
            self.store.save(self._session(f"s{i}", title=f"T{i}"))
        summaries = self.store.list(limit=2)
        self.assertEqual(len(summaries), 2)
        # Most recently updated first.
        self.assertEqual(summaries[0].session_id, "s2")
        page2 = self.store.list(limit=2, offset=2)
        self.assertEqual(len(page2), 1)

    def test_summary_has_preview_and_count(self):
        self.store.save(self._session("s1", user_text="what is the weather"))
        summary = self.store.list()[0]
        self.assertEqual(summary.message_count, 2)
        self.assertIn("weather", summary.preview)

    def test_delete_removes_row(self):
        self.store.save(self._session("s1"))
        self.store.delete("s1")
        self.assertIsNone(self.store.load("s1"))

    def test_delete_unknown_is_noop(self):
        # Should not raise.
        self.store.delete("ghost")

    def test_search_matches_title_and_preview(self):
        self.store.save(self._session("s1", title="Budget review", user_text="quarterly numbers"))
        self.store.save(self._session("s2", title="Unrelated", user_text="hello"))
        by_title = self.store.search("Budget")
        self.assertEqual([s.session_id for s in by_title], ["s1"])
        by_preview = self.store.search("quarterly")
        self.assertEqual([s.session_id for s in by_preview], ["s1"])

    def test_search_no_match_returns_empty(self):
        self.store.save(self._session("s1"))
        self.assertEqual(self.store.search("zzz"), [])

    def test_reopen_persists_data(self):
        self.store.save(self._session("s1", title="Persisted"))
        reopened = SQLiteSessionStore(self.db_path)
        self.assertEqual(reopened.load("s1").title, "Persisted")


class TestSQLiteSessionStoreOwnerScoping(unittest.TestCase):
    """Owner-scoped stores: visibility, hijack protection, migration."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "sessions.db"
        self.alice = SQLiteSessionStore(self.db_path, owner="alice@example.com")
        self.bob = SQLiteSessionStore(self.db_path, owner="bob@example.com")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _session(sid: str, title: str = "T") -> ChatSession:
        session = ChatSession(session_id=sid, title=title)
        session.add_user_message("hello")
        return session

    def test_scoped_visibility(self):
        self.alice.save(self._session("s-a", title="Alice's"))

        self.assertIsNotNone(self.alice.load("s-a"))
        self.assertIsNone(self.bob.load("s-a"))
        self.assertEqual([s.session_id for s in self.alice.list()], ["s-a"])
        self.assertEqual(self.bob.list(), [])
        self.assertEqual(self.bob.search("Alice"), [])

    def test_save_hijack_raises_and_preserves_original(self):
        self.alice.save(self._session("s-a", title="Original"))

        with self.assertRaises(SessionOwnershipError):
            self.bob.save(self._session("s-a", title="Hijacked"))

        self.assertEqual(self.alice.load("s-a").title, "Original")
        self.assertIsNone(self.bob.load("s-a"))

    def test_scoped_delete_ignores_foreign_session(self):
        self.alice.save(self._session("s-a"))
        self.bob.delete("s-a")
        self.assertIsNotNone(self.alice.load("s-a"))

    def test_owner_resave_updates_own_session(self):
        self.alice.save(self._session("s-a", title="First"))
        self.alice.save(self._session("s-a", title="Second"))
        self.assertEqual(self.alice.load("s-a").title, "Second")

    def test_unscoped_store_sees_everything_but_keeps_owner(self):
        self.alice.save(self._session("s-a", title="Alice's"))
        unscoped = SQLiteSessionStore(self.db_path)

        self.assertIsNotNone(unscoped.load("s-a"))
        unscoped.save(self._session("s-a", title="Updated by system"))

        # Unscoped save updates content but never strips ownership.
        self.assertEqual(self.alice.load("s-a").title, "Updated by system")
        self.assertIsNone(self.bob.load("s-a"))

    def test_old_schema_db_is_migrated_on_open(self):
        old_path = Path(self._tmp.name) / "old.db"
        conn = sqlite3.connect(old_path)
        conn.execute(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                preview TEXT NOT NULL DEFAULT '',
                data TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        store = SQLiteSessionStore(old_path, owner="alice@example.com")
        store.save(self._session("s-new"))
        self.assertIsNotNone(store.load("s-new"))


if __name__ == "__main__":
    unittest.main()
