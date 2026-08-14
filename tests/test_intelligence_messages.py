"""Tests for the provider-neutral conversation message primitives."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from openbench.intelligence.messages import Message, MessageRole


class TestMessageRole(unittest.TestCase):
    def test_role_values_are_wire_names(self):
        self.assertEqual(
            {role.value for role in MessageRole},
            {"system", "user", "assistant", "tool"},
        )


class TestMessageToDict(unittest.TestCase):
    def test_minimal_message(self):
        message = Message(role=MessageRole.USER, content="hello")
        self.assertEqual(message.to_dict(), {"role": "user", "content": "hello"})

    def test_optional_fields_are_omitted_when_unset(self):
        payload = Message(role=MessageRole.ASSISTANT, content="hi").to_dict()
        for absent in ("name", "tool_call_id", "tool_calls", "raw_content", "media"):
            self.assertNotIn(absent, payload)

    def test_tool_message_round_trip(self):
        message = Message(
            role=MessageRole.TOOL,
            content='{"ok": true}',
            name="search",
            tool_call_id="call-1",
        )
        self.assertEqual(
            message.to_dict(),
            {
                "role": "tool",
                "content": '{"ok": true}',
                "name": "search",
                "tool_call_id": "call-1",
            },
        )

    def test_tool_calls_are_included(self):
        calls = [{"id": "call-1", "function": {"name": "search", "arguments": "{}"}}]
        payload = Message(role=MessageRole.ASSISTANT, content="", tool_calls=calls).to_dict()
        self.assertEqual(payload["tool_calls"], calls)

    def test_raw_content_kept_only_when_not_none(self):
        payload = Message(role=MessageRole.ASSISTANT, content="x", raw_content=0).to_dict()
        # Falsy-but-not-None values must survive: 0 is a legitimate payload.
        self.assertEqual(payload["raw_content"], 0)

    def test_media_is_serialized_via_to_dict(self):
        media_item = SimpleNamespace(to_dict=lambda: {"kind": "image", "url": "u"})
        payload = Message(role=MessageRole.USER, content="see", media=[media_item]).to_dict()
        self.assertEqual(payload["media"], [{"kind": "image", "url": "u"}])


if __name__ == "__main__":
    unittest.main()
