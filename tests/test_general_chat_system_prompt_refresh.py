"""Tests for refreshing a session's persisted system prompt.

Sessions store their system message on first use. Before this, a chat
created before a prompt change kept the old text forever — the tool
schemas still shipped, but every instruction telling the model *when* to
call them was missing, which is why existing sessions never produced
files.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_EXAMPLE_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(_EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_SRC))

from general_chat.server.handler import refresh_system_message  # noqa: E402

from openbench.intelligence.base import Message, MessageRole  # noqa: E402


class TestRefreshSystemMessage(unittest.TestCase):
    def test_replaces_a_stale_system_message(self):
        messages = [
            Message(role=MessageRole.SYSTEM, content="old prompt"),
            Message(role=MessageRole.USER, content="hi"),
        ]
        self.assertTrue(refresh_system_message(messages, "new prompt"))
        self.assertEqual(messages[0].content, "new prompt")
        self.assertEqual(messages[0].role, MessageRole.SYSTEM)

    def test_preserves_the_rest_of_the_history(self):
        messages = [
            Message(role=MessageRole.SYSTEM, content="old"),
            Message(role=MessageRole.USER, content="hi"),
            Message(role=MessageRole.ASSISTANT, content="hello"),
        ]
        refresh_system_message(messages, "new")
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[1].content, "hi")
        self.assertEqual(messages[2].content, "hello")

    def test_up_to_date_prompt_is_left_alone(self):
        messages = [Message(role=MessageRole.SYSTEM, content="same")]
        self.assertFalse(refresh_system_message(messages, "same"))

    def test_empty_history_is_not_rewritten(self):
        messages: list[Message] = []
        self.assertFalse(refresh_system_message(messages, "new"))
        self.assertEqual(messages, [])

    def test_history_without_a_leading_system_message_is_untouched(self):
        messages = [Message(role=MessageRole.USER, content="hi")]
        self.assertFalse(refresh_system_message(messages, "new"))
        self.assertEqual(messages[0].role, MessageRole.USER)


if __name__ == "__main__":
    unittest.main()
