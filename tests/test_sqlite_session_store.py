"""Tests for SQLiteSessionStore."""

import tempfile
import unittest
from pathlib import Path

from openbench.chat.session import ChatSession
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


if __name__ == "__main__":
    unittest.main()
