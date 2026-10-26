"""Tests for the AGUISessionHandler REST bridge."""

import unittest

from openbench.chat.session import ChatSession
from openbench.chat.transport.sessions import AGUISessionHandler


class _FakeStore:
    """Minimal in-memory SessionStore stand-in."""

    def __init__(self):
        self.sessions: dict[str, ChatSession] = {}
        self.deleted: list[str] = []

    def list(self, limit=50, offset=0):
        items = list(self.sessions.values())
        return items[offset : offset + limit]

    def load(self, session_id):
        return self.sessions.get(session_id)

    def delete(self, session_id):
        self.deleted.append(session_id)
        self.sessions.pop(session_id, None)

    def search(self, query, limit=20):
        return [s for s in self.sessions.values() if query in s.title][:limit]


class TestAGUISessionHandlerNoStore(unittest.TestCase):
    """A handler with no store returns safe empty defaults."""

    def setUp(self):
        self.handler = AGUISessionHandler(session_store=None)

    def test_list_empty(self):
        self.assertEqual(self.handler.list(), [])

    def test_get_none(self):
        self.assertIsNone(self.handler.get("anything"))

    def test_delete_is_noop(self):
        # Should not raise.
        self.handler.delete("anything")

    def test_search_empty(self):
        self.assertEqual(self.handler.search("q"), [])


class TestAGUISessionHandlerWithStore(unittest.TestCase):
    """A handler delegates to its store and serializes to dicts."""

    def setUp(self):
        self.store = _FakeStore()
        self.session = ChatSession(session_id="s1", title="Hello world")
        self.session.add_user_message("hi")
        self.store.sessions["s1"] = self.session
        self.handler = AGUISessionHandler(session_store=self.store)

    def test_list_returns_dicts(self):
        result = self.handler.list()
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)
        self.assertEqual(result[0]["sessionId"], "s1")

    def test_get_returns_full_dict(self):
        result = self.handler.get("s1")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["sessionId"], "s1")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.handler.get("missing"))

    def test_delete_delegates(self):
        self.handler.delete("s1")
        self.assertIn("s1", self.store.deleted)

    def test_search_returns_dicts(self):
        result = self.handler.search("Hello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sessionId"], "s1")

    def test_search_no_match(self):
        self.assertEqual(self.handler.search("nomatch"), [])


if __name__ == "__main__":
    unittest.main()
