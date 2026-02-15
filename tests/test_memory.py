"""Tests for persistent memory module."""

from __future__ import annotations

import os
import tempfile
import unittest

from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.memory import (
    MemoryStore,
    PersistentMemory,
    SQLiteMemoryStore,
)


class TestSQLiteMemoryStore(unittest.TestCase):
    """Test SQLiteMemoryStore."""

    def setUp(self):
        """Create a temporary database for each test."""
        fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = SQLiteMemoryStore(db_path=self.tmp_path)

    def tearDown(self):
        """Remove temporary database."""
        os.unlink(self.tmp_path)

    def test_save_and_load(self):
        """Test saving and loading messages."""
        messages = [
            Message(role=MessageRole.USER, content="Hello"),
            Message(role=MessageRole.ASSISTANT, content="Hi there!"),
        ]
        self.store.save("session-1", messages)

        loaded = self.store.load("session-1")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].role, MessageRole.USER)
        self.assertEqual(loaded[0].content, "Hello")
        self.assertEqual(loaded[1].role, MessageRole.ASSISTANT)
        self.assertEqual(loaded[1].content, "Hi there!")

    def test_load_empty_session(self):
        """Test loading a session with no messages."""
        loaded = self.store.load("nonexistent")
        self.assertEqual(loaded, [])

    def test_save_with_tool_fields(self):
        """Test saving messages with tool-related fields."""
        messages = [
            Message(
                role=MessageRole.TOOL,
                content='{"result": "42"}',
                name="calculate",
                tool_call_id="call_0",
            ),
            Message(
                role=MessageRole.ASSISTANT,
                content="The answer is 42",
                tool_calls=[{"id": "call_0", "name": "calculate", "arguments": {"x": 6, "y": 7}}],
            ),
        ]
        self.store.save("session-1", messages)

        loaded = self.store.load("session-1")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].name, "calculate")
        self.assertEqual(loaded[0].tool_call_id, "call_0")
        self.assertEqual(loaded[1].tool_calls[0]["name"], "calculate")

    def test_multiple_sessions(self):
        """Test storing messages in multiple sessions."""
        self.store.save("session-1", [Message(role=MessageRole.USER, content="Hello")])
        self.store.save("session-2", [Message(role=MessageRole.USER, content="Bonjour")])

        s1 = self.store.load("session-1")
        s2 = self.store.load("session-2")
        self.assertEqual(len(s1), 1)
        self.assertEqual(s1[0].content, "Hello")
        self.assertEqual(len(s2), 1)
        self.assertEqual(s2[0].content, "Bonjour")

    def test_search(self):
        """Test keyword search across sessions."""
        self.store.save("s1", [Message(role=MessageRole.USER, content="Python programming")])
        self.store.save("s2", [Message(role=MessageRole.USER, content="Java programming")])
        self.store.save("s3", [Message(role=MessageRole.USER, content="Cooking recipes")])

        results = self.store.search("programming")
        self.assertEqual(len(results), 2)

    def test_search_limit(self):
        """Test search respects limit."""
        for i in range(10):
            self.store.save("s", [Message(role=MessageRole.USER, content=f"Item {i}")])

        results = self.store.search("Item", limit=3)
        self.assertEqual(len(results), 3)

    def test_search_no_results(self):
        """Test search with no matches."""
        self.store.save("s1", [Message(role=MessageRole.USER, content="Hello")])
        results = self.store.search("xyz_no_match")
        self.assertEqual(results, [])

    def test_list_sessions(self):
        """Test listing all session IDs."""
        self.store.save("alpha", [Message(role=MessageRole.USER, content="a")])
        self.store.save("beta", [Message(role=MessageRole.USER, content="b")])
        self.store.save("alpha", [Message(role=MessageRole.USER, content="c")])

        sessions = self.store.list_sessions()
        self.assertEqual(sorted(sessions), ["alpha", "beta"])

    def test_delete_session(self):
        """Test deleting a session."""
        self.store.save("to-delete", [Message(role=MessageRole.USER, content="bye")])
        self.store.save("to-keep", [Message(role=MessageRole.USER, content="hi")])

        self.store.delete_session("to-delete")

        self.assertEqual(self.store.load("to-delete"), [])
        self.assertEqual(len(self.store.load("to-keep")), 1)

    def test_append_to_existing_session(self):
        """Test appending messages to an existing session."""
        self.store.save("s1", [Message(role=MessageRole.USER, content="First")])
        self.store.save("s1", [Message(role=MessageRole.ASSISTANT, content="Second")])

        loaded = self.store.load("s1")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].content, "First")
        self.assertEqual(loaded[1].content, "Second")

    def test_is_abstract_subclass(self):
        """Test SQLiteMemoryStore is a MemoryStore."""
        self.assertIsInstance(self.store, MemoryStore)


class TestPersistentMemory(unittest.TestCase):
    """Test PersistentMemory (AgentMemory with persistence)."""

    def setUp(self):
        """Create a temporary database."""
        fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = SQLiteMemoryStore(db_path=self.tmp_path)

    def tearDown(self):
        """Remove temporary database."""
        os.unlink(self.tmp_path)

    def test_add_persists_automatically(self):
        """Test that add() persists messages to store."""
        memory = PersistentMemory(store=self.store, session_id="test")
        memory.add_user("Hello")
        memory.add_assistant("Hi!")

        # Load from store directly
        loaded = self.store.load("test")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].content, "Hello")
        self.assertEqual(loaded[1].content, "Hi!")

    def test_loads_previous_messages(self):
        """Test that PersistentMemory loads existing messages on init."""
        # Save some messages first
        self.store.save(
            "test",
            [
                Message(role=MessageRole.SYSTEM, content="You are helpful"),
                Message(role=MessageRole.USER, content="Question"),
            ],
        )

        # Create memory - should load previous messages
        memory = PersistentMemory(store=self.store, session_id="test")
        messages = memory.get_messages()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["content"], "Question")

    def test_survives_recreation(self):
        """Test messages persist across PersistentMemory instances."""
        mem1 = PersistentMemory(store=self.store, session_id="persist-test")
        mem1.add_user("Remember this")

        # Create a new instance pointing to the same session
        mem2 = PersistentMemory(store=self.store, session_id="persist-test")
        messages = mem2.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "Remember this")

    def test_clear_deletes_from_store(self):
        """Test clear() removes messages from both memory and store."""
        memory = PersistentMemory(store=self.store, session_id="clear-test")
        memory.add_system("System prompt")
        memory.add_user("Hello")

        memory.clear()

        # In-memory should be cleared (system preserved by AgentMemory.clear)
        self.assertLessEqual(len(memory.messages), 1)

        # Store should be empty
        loaded = self.store.load("clear-test")
        self.assertEqual(loaded, [])

    def test_search_history(self):
        """Test searching across sessions."""
        mem1 = PersistentMemory(store=self.store, session_id="s1")
        mem1.add_user("Python is great")

        mem2 = PersistentMemory(store=self.store, session_id="s2")
        mem2.add_user("Python rocks")

        results = mem2.search_history("Python")
        self.assertEqual(len(results), 2)

    def test_max_messages_respected(self):
        """Test that max_messages trimming still works."""
        memory = PersistentMemory(store=self.store, session_id="trim-test", max_messages=5)
        for i in range(10):
            memory.add_user(f"Message {i}")

        self.assertLessEqual(len(memory.messages), 5)

    def test_different_sessions_isolated(self):
        """Test messages don't leak between sessions."""
        mem1 = PersistentMemory(store=self.store, session_id="isolated-1")
        mem1.add_user("Session 1 only")

        mem2 = PersistentMemory(store=self.store, session_id="isolated-2")
        self.assertEqual(len(mem2.messages), 0)

    def test_tool_result_persisted(self):
        """Test tool results are properly persisted."""
        memory = PersistentMemory(store=self.store, session_id="tool-test")
        memory.add_tool_result("call_0", "search", '{"answer": "42"}')

        loaded = self.store.load("tool-test")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].role, MessageRole.TOOL)
        self.assertEqual(loaded[0].name, "search")
        self.assertEqual(loaded[0].tool_call_id, "call_0")


if __name__ == "__main__":
    unittest.main()
