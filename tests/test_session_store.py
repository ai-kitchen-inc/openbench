"""Tests for SessionStore ABC, SQLiteSessionStore, and AGUISessionHandler."""

import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from openbench.chat.session import Attachment, ChatSession
from openbench.chat.session_store import SessionStore, SessionSummary
from openbench.chat.stores.sqlite import SQLiteSessionStore
from openbench.chat.transport.sessions import AGUISessionHandler


def _make_session(title: str = "Demo") -> ChatSession:
    session = ChatSession(title=title)
    session.add_user_message("hello world")
    session.add_assistant_message(
        content="hi back",
        surfaces=[{"surfaceId": "s-1"}],
        metadata={"model": "test"},
    )
    return session


class TestSessionSummary(unittest.TestCase):
    """SessionSummary serialization."""

    def test_to_dict(self):
        now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
        s = SessionSummary(
            session_id="abc",
            title="Q1 Review",
            created_at=now,
            updated_at=now,
            message_count=4,
            preview="Tell me about Q1",
        )
        d = s.to_dict()
        self.assertEqual(d["sessionId"], "abc")
        self.assertEqual(d["title"], "Q1 Review")
        self.assertEqual(d["messageCount"], 4)
        self.assertEqual(d["preview"], "Tell me about Q1")
        self.assertEqual(d["createdAt"], "2026-04-17T10:00:00+00:00")


class TestSQLiteSessionStoreRoundtrip(unittest.TestCase):
    """Basic save/load/list/delete contract."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "sessions.db")
        self.store = SQLiteSessionStore(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_save_and_load(self):
        session = _make_session("Sales")
        self.store.save(session)
        reloaded = self.store.load(session.session_id)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None  # narrow for type checker
        self.assertEqual(reloaded.session_id, session.session_id)
        self.assertEqual(reloaded.title, "Sales")
        self.assertEqual(len(reloaded.messages), 2)
        self.assertEqual(reloaded.messages[0].content, "hello world")
        self.assertEqual(reloaded.messages[1].content, "hi back")

    def test_load_unknown_returns_none(self):
        self.assertIsNone(self.store.load("nonexistent"))

    def test_save_is_idempotent_and_updates(self):
        session = _make_session("v1")
        self.store.save(session)
        session.title = "v2"
        session.add_user_message("another message")
        self.store.save(session)
        reloaded = self.store.load(session.session_id)
        assert reloaded is not None
        self.assertEqual(reloaded.title, "v2")
        self.assertEqual(len(reloaded.messages), 3)

    def test_delete_removes_session(self):
        session = _make_session()
        self.store.save(session)
        self.store.delete(session.session_id)
        self.assertIsNone(self.store.load(session.session_id))

    def test_delete_unknown_is_noop(self):
        self.store.delete("nope")  # must not raise

    def test_list_orders_by_updated_desc(self):
        first = _make_session("First")
        self.store.save(first)
        time.sleep(0.01)  # ensure distinct ISO timestamps
        second = _make_session("Second")
        self.store.save(second)

        summaries = self.store.list()
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0].session_id, second.session_id)
        self.assertEqual(summaries[1].session_id, first.session_id)

    def test_list_respects_limit_and_offset(self):
        ids = []
        for i in range(5):
            s = _make_session(f"S{i}")
            self.store.save(s)
            ids.append(s.session_id)
            time.sleep(0.002)

        page = self.store.list(limit=2, offset=1)
        self.assertEqual(len(page), 2)
        # ids[-1] is newest; offset=1 skips it → next two are ids[-2], ids[-3]
        self.assertEqual(page[0].session_id, ids[-2])
        self.assertEqual(page[1].session_id, ids[-3])

    def test_summary_includes_preview_and_count(self):
        session = _make_session("Preview")
        self.store.save(session)
        summary = self.store.list()[0]
        self.assertEqual(summary.message_count, 2)
        self.assertEqual(summary.preview, "hello world")

    def test_preview_truncates_long_message(self):
        session = ChatSession(title="Long")
        session.add_user_message("x" * 500)
        self.store.save(session)
        summary = self.store.list()[0]
        self.assertEqual(len(summary.preview), 120)
        self.assertTrue(summary.preview.endswith("\u2026"))

    def test_preview_handles_session_with_no_user_message(self):
        session = ChatSession(title="NoUser")
        session.add_assistant_message(content="assistant-only")
        self.store.save(session)
        summary = self.store.list()[0]
        self.assertEqual(summary.preview, "")

    def test_roundtrip_preserves_attachments(self):
        attachment = Attachment(
            id="att-1",
            type="file",
            name="doc.pdf",
            url="https://example.com/doc.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )
        session = ChatSession(title="Attached")
        session.add_user_message("see file", attachments=[attachment])
        self.store.save(session)

        reloaded = self.store.load(session.session_id)
        assert reloaded is not None
        self.assertEqual(len(reloaded.messages[0].attachments or []), 1)
        self.assertEqual(reloaded.messages[0].attachments[0].name, "doc.pdf")

    def test_search_matches_title_and_preview(self):
        a = _make_session("Quarterly Review")
        self.store.save(a)
        b = ChatSession(title="Other")
        b.add_user_message("about quarterly numbers")
        self.store.save(b)

        hits = {s.session_id for s in self.store.search("quarterly")}
        self.assertEqual(hits, {a.session_id, b.session_id})

    def test_search_empty_query_matches_everything(self):
        self.store.save(_make_session("A"))
        self.store.save(_make_session("B"))
        self.assertEqual(len(self.store.search("")), 2)


class TestSQLiteSessionStoreFileSystem(unittest.TestCase):
    """Ensure parent directory is created on init."""

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "deeply" / "nested" / "sessions.db")
            store = SQLiteSessionStore(db_path)
            store.save(_make_session())
            self.assertTrue(Path(db_path).exists())


class TestAGUISessionHandler(unittest.TestCase):
    """Handler thin-delegates to SessionStore and gracefully handles None."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteSessionStore(str(Path(self._tmpdir.name) / "sessions.db"))
        self.handler = AGUISessionHandler(session_store=self.store)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_list_returns_dicts(self):
        self.store.save(_make_session("A"))
        result = self.handler.list()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "A")
        # Ensure serialization (datetimes as ISO strings)
        self.assertIsInstance(result[0]["createdAt"], str)

    def test_get_returns_dict(self):
        session = _make_session("X")
        self.store.save(session)
        result = self.handler.get(session.session_id)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["title"], "X")
        self.assertEqual(len(result["messages"]), 2)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.handler.get("missing"))

    def test_delete_removes(self):
        session = _make_session()
        self.store.save(session)
        self.handler.delete(session.session_id)
        self.assertIsNone(self.handler.get(session.session_id))

    def test_search_returns_dicts(self):
        self.store.save(_make_session("Quarterly"))
        result = self.handler.search("quart")
        self.assertEqual(len(result), 1)

    def test_no_store_returns_empty(self):
        handler = AGUISessionHandler(session_store=None)
        self.assertEqual(handler.list(), [])
        self.assertIsNone(handler.get("anything"))
        handler.delete("anything")  # no-op, must not raise
        self.assertEqual(handler.search("anything"), [])


class TestSessionStoreABC(unittest.TestCase):
    """Ensure the ABC cannot be instantiated directly."""

    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            SessionStore()  # type: ignore[abstract]


if __name__ == "__main__":
    unittest.main()
