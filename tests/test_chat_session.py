"""Tests for chat session, message, and attachment."""

import unittest

from openbench.chat.session import Attachment, ChatMessage, ChatSession, MessageRole


class TestMessageRole(unittest.TestCase):
    """Tests for MessageRole enum."""

    def test_values(self):
        self.assertEqual(MessageRole.USER.value, "user")
        self.assertEqual(MessageRole.ASSISTANT.value, "assistant")
        self.assertEqual(MessageRole.SYSTEM.value, "system")
        self.assertEqual(MessageRole.TOOL.value, "tool")

    def test_from_string(self):
        self.assertEqual(MessageRole("user"), MessageRole.USER)
        self.assertEqual(MessageRole("assistant"), MessageRole.ASSISTANT)


class TestAttachment(unittest.TestCase):
    """Tests for Attachment dataclass."""

    def test_to_dict(self):
        attachment = Attachment(
            id="att-1",
            type="file",
            name="report.pdf",
            url="https://example.com/report.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )
        d = attachment.to_dict()
        self.assertEqual(d["id"], "att-1")
        self.assertEqual(d["type"], "file")
        self.assertEqual(d["name"], "report.pdf")
        self.assertEqual(d["mimeType"], "application/pdf")
        self.assertEqual(d["sizeBytes"], 1024)

    def test_to_dict_without_size(self):
        attachment = Attachment(
            id="att-2",
            type="image",
            name="photo.jpg",
            url="https://example.com/photo.jpg",
            mime_type="image/jpeg",
        )
        d = attachment.to_dict()
        self.assertNotIn("sizeBytes", d)

    def test_roundtrip(self):
        original = Attachment(
            id="att-3",
            type="audio",
            name="clip.mp3",
            url="https://example.com/clip.mp3",
            mime_type="audio/mpeg",
            size_bytes=2048,
        )
        restored = Attachment.from_dict(original.to_dict())
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.type, original.type)
        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.url, original.url)
        self.assertEqual(restored.mime_type, original.mime_type)
        self.assertEqual(restored.size_bytes, original.size_bytes)


class TestChatMessage(unittest.TestCase):
    """Tests for ChatMessage dataclass."""

    def test_basic_message(self):
        msg = ChatMessage(
            id="msg-1",
            role=MessageRole.USER,
            content="Hello!",
        )
        self.assertEqual(msg.role, MessageRole.USER)
        self.assertEqual(msg.content, "Hello!")
        self.assertIsNone(msg.surfaces)
        self.assertIsNone(msg.attachments)

    def test_to_dict(self):
        msg = ChatMessage(
            id="msg-2",
            role=MessageRole.ASSISTANT,
            content="Hi there!",
            surfaces=[{"surfaceId": "s1", "components": []}],
            metadata={"model": "gemini-2.5-flash"},
        )
        d = msg.to_dict()
        self.assertEqual(d["id"], "msg-2")
        self.assertEqual(d["role"], "assistant")
        self.assertEqual(d["content"], "Hi there!")
        self.assertEqual(len(d["surfaces"]), 1)
        self.assertEqual(d["metadata"]["model"], "gemini-2.5-flash")
        self.assertIn("timestamp", d)

    def test_to_dict_minimal(self):
        msg = ChatMessage(id="msg-3", role=MessageRole.USER, content="test")
        d = msg.to_dict()
        self.assertNotIn("surfaces", d)
        self.assertNotIn("attachments", d)
        self.assertNotIn("metadata", d)

    def test_roundtrip(self):
        original = ChatMessage(
            id="msg-4",
            role=MessageRole.ASSISTANT,
            content="Here's the chart",
            surfaces=[{"surfaceId": "s1"}],
            attachments=[
                Attachment(
                    id="att-1",
                    type="file",
                    name="data.csv",
                    url="https://example.com/data.csv",
                    mime_type="text/csv",
                )
            ],
            metadata={"tokensUsed": 100},
        )
        restored = ChatMessage.from_dict(original.to_dict())
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.role, original.role)
        self.assertEqual(restored.content, original.content)
        self.assertEqual(restored.surfaces, original.surfaces)
        self.assertEqual(len(restored.attachments), 1)
        self.assertEqual(restored.attachments[0].name, "data.csv")
        self.assertEqual(restored.metadata["tokensUsed"], 100)


class TestChatSession(unittest.TestCase):
    """Tests for ChatSession."""

    def test_create_session(self):
        session = ChatSession()
        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.title, "New Chat")
        self.assertEqual(len(session), 0)

    def test_create_session_with_id(self):
        session = ChatSession(session_id="test-session", title="Test Chat")
        self.assertEqual(session.session_id, "test-session")
        self.assertEqual(session.title, "Test Chat")

    def test_add_user_message(self):
        session = ChatSession()
        msg = session.add_user_message("Hello!")
        self.assertEqual(msg.role, MessageRole.USER)
        self.assertEqual(msg.content, "Hello!")
        self.assertEqual(len(session), 1)

    def test_add_user_message_with_attachments(self):
        session = ChatSession()
        attachment = Attachment(
            id="att-1",
            type="file",
            name="doc.pdf",
            url="https://example.com/doc.pdf",
            mime_type="application/pdf",
        )
        msg = session.add_user_message("See attached", attachments=[attachment])
        self.assertEqual(len(msg.attachments), 1)
        self.assertEqual(msg.attachments[0].name, "doc.pdf")

    def test_add_assistant_message(self):
        session = ChatSession()
        surfaces = [{"surfaceId": "s1", "components": []}]
        msg = session.add_assistant_message("Here's your data", surfaces=surfaces)
        self.assertEqual(msg.role, MessageRole.ASSISTANT)
        self.assertEqual(msg.surfaces, surfaces)

    def test_add_system_message(self):
        session = ChatSession()
        msg = session.add_system_message("You are a helpful assistant")
        self.assertEqual(msg.role, MessageRole.SYSTEM)

    def test_get_context_window(self):
        session = ChatSession()
        session.add_system_message("System prompt")
        for i in range(10):
            session.add_user_message(f"Message {i}")
            session.add_assistant_message(f"Reply {i}")

        # Should get system + last N messages
        window = session.get_context_window(max_messages=5)
        self.assertEqual(len(window), 5)
        self.assertEqual(window[0].role, MessageRole.SYSTEM)

    def test_get_context_window_preserves_system(self):
        session = ChatSession()
        session.add_system_message("System prompt")
        for i in range(3):
            session.add_user_message(f"Msg {i}")

        window = session.get_context_window(max_messages=2)
        self.assertEqual(len(window), 2)
        self.assertEqual(window[0].role, MessageRole.SYSTEM)
        self.assertEqual(window[1].content, "Msg 2")

    def test_roundtrip(self):
        session = ChatSession(session_id="s1", title="Test")
        session.add_user_message("Hello")
        session.add_assistant_message("Hi!")

        data = session.to_dict()
        restored = ChatSession.from_dict(data)

        self.assertEqual(restored.session_id, "s1")
        self.assertEqual(restored.title, "Test")
        self.assertEqual(len(restored), 2)
        self.assertEqual(restored.messages[0].content, "Hello")
        self.assertEqual(restored.messages[1].content, "Hi!")

    def test_updated_at_changes(self):
        session = ChatSession()
        initial = session.updated_at
        session.add_user_message("test")
        self.assertGreaterEqual(session.updated_at, initial)

    def test_metadata_defaults_empty(self):
        session = ChatSession()
        self.assertEqual(session.metadata, {})
        # Empty metadata must not appear in the serialized form (old rows
        # and their consumers stay byte-identical).
        self.assertNotIn("metadata", session.to_dict())

    def test_metadata_roundtrip(self):
        session = ChatSession(session_id="s1", metadata={"agentId": "finance-analyst"})
        data = session.to_dict()
        self.assertEqual(data["metadata"], {"agentId": "finance-analyst"})
        restored = ChatSession.from_dict(data)
        self.assertEqual(restored.metadata, {"agentId": "finance-analyst"})

    def test_metadata_absent_key_defaults(self):
        restored = ChatSession.from_dict({"sessionId": "s1", "title": "T", "messages": []})
        self.assertEqual(restored.metadata, {})

    def test_metadata_non_dict_tolerated(self):
        restored = ChatSession.from_dict(
            {"sessionId": "s1", "title": "T", "messages": [], "metadata": "junk"}
        )
        self.assertEqual(restored.metadata, {})

    def test_repr(self):
        session = ChatSession(session_id="abc")
        session.add_user_message("hello")
        self.assertIn("abc", repr(session))
        self.assertIn("1", repr(session))


class TestTolerantDeserialization(unittest.TestCase):
    """Loading must degrade on partial corruption, not raise (history robustness)."""

    def test_skips_malformed_message_keeps_valid(self):
        data = {
            "sessionId": "s1",
            "title": "T",
            "createdAt": "2026-06-30T00:00:00+00:00",
            "updatedAt": "2026-06-30T00:00:00+00:00",
            "messages": [
                {"id": "m1", "role": "user", "content": "hi", "timestamp": "2026-06-30T00:00:00+00:00"},
                {"id": "m2", "role": "bogus-role", "content": "x", "timestamp": "2026-06-30T00:00:00+00:00"},
                {"id": "m3", "role": "assistant", "content": "ok", "timestamp": "2026-06-30T00:00:00+00:00"},
            ],
        }
        restored = ChatSession.from_dict(data)
        # The bad-role message is dropped; the two valid ones survive.
        self.assertEqual(len(restored), 2)
        self.assertEqual(restored.messages[0].content, "hi")
        self.assertEqual(restored.messages[1].content, "ok")

    def test_missing_top_level_fields_do_not_raise(self):
        restored = ChatSession.from_dict({"messages": []})
        self.assertTrue(restored.session_id)  # defaulted uuid
        self.assertIsNotNone(restored.created_at)
        self.assertIsNotNone(restored.updated_at)

    def test_message_defaults_missing_fields(self):
        msg = ChatMessage.from_dict({"role": "user"})
        self.assertTrue(msg.id)  # defaulted uuid
        self.assertEqual(msg.content, "")
        self.assertIsNotNone(msg.timestamp)

    def test_message_bad_timestamp_falls_back(self):
        msg = ChatMessage.from_dict(
            {"id": "m", "role": "user", "content": "c", "timestamp": "not-a-date"}
        )
        self.assertIsNotNone(msg.timestamp)

    def test_message_drops_bad_attachment(self):
        msg = ChatMessage.from_dict(
            {
                "id": "m",
                "role": "user",
                "content": "c",
                "timestamp": "2026-06-30T00:00:00+00:00",
                "attachments": ["not-a-dict"],
            }
        )
        # Bad attachment dropped, message still loads.
        self.assertIsNone(msg.attachments)


if __name__ == "__main__":
    unittest.main()
