"""Tests for ChatSSEHandler."""

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from openbench.chat.transport.sse import ChatSSEHandler


class MockAsyncStream:
    """Mock async iterator that yields JSON lines like ChatEngine.async_stream()."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._index]
        self._index += 1
        return line


class MockAsyncStreamError:
    """Mock async iterator that raises after yielding some lines."""

    def __init__(self, lines: list[str], error: Exception):
        self._lines = lines
        self._error = error
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._lines):
            raise self._error
        line = self._lines[self._index]
        self._index += 1
        return line


def _run(coro):
    """Helper to run async code in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect(handler: ChatSSEHandler, data: dict[str, Any]) -> list[str]:
    """Collect all SSE events from handler.stream()."""
    events = []
    async for event in handler.stream(data):
        events.append(event)
    return events


class TestChatSSEHandlerInit(unittest.TestCase):
    """Tests for ChatSSEHandler initialization."""

    def test_init_stores_engine(self):
        engine = MagicMock()
        handler = ChatSSEHandler(engine=engine)
        self.assertIs(handler.engine, engine)


class TestChatSSEHandlerStream(unittest.TestCase):
    """Tests for ChatSSEHandler.stream()."""

    def test_stream_yields_sse_format(self):
        """Each line should be wrapped as 'data: {json}\\n\\n'."""
        lines = [
            json.dumps({"type": "stream_start", "messageId": "msg-1"}),
            json.dumps({"type": "stream_end", "messageId": "msg-1"}),
        ]
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream(lines))

        handler = ChatSSEHandler(engine=engine)
        events = _run(_collect(handler, {"content": "Hello"}))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], f"data: {lines[0]}\n\n")
        self.assertEqual(events[1], f"data: {lines[1]}\n\n")

    def test_stream_passes_content(self):
        """Content from data dict should be passed to engine.async_stream()."""
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream([]))

        handler = ChatSSEHandler(engine=engine)
        _run(_collect(handler, {"content": "Show chart"}))

        call_args = engine.async_stream.call_args[0][0]
        self.assertEqual(call_args["content"], "Show chart")

    def test_stream_passes_session_id(self):
        """sessionId (camelCase) should be mapped to session_id (snake_case)."""
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream([]))

        handler = ChatSSEHandler(engine=engine)
        _run(_collect(handler, {"content": "Hi", "sessionId": "sess-abc"}))

        call_args = engine.async_stream.call_args[0][0]
        self.assertEqual(call_args["session_id"], "sess-abc")

    def test_stream_passes_attachments(self):
        """Attachments should be forwarded to engine."""
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream([]))
        attachments = [{"id": "a1", "name": "doc.pdf", "url": "/files/doc.pdf"}]

        handler = ChatSSEHandler(engine=engine)
        _run(_collect(handler, {"content": "Hi", "attachments": attachments}))

        call_args = engine.async_stream.call_args[0][0]
        self.assertEqual(call_args["attachments"], attachments)

    def test_stream_defaults_content_to_empty(self):
        """Missing content should default to empty string."""
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream([]))

        handler = ChatSSEHandler(engine=engine)
        _run(_collect(handler, {}))

        call_args = engine.async_stream.call_args[0][0]
        self.assertEqual(call_args["content"], "")

    def test_stream_defaults_optional_fields_to_none(self):
        """Missing sessionId and attachments should be None."""
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream([]))

        handler = ChatSSEHandler(engine=engine)
        _run(_collect(handler, {"content": "Hi"}))

        call_args = engine.async_stream.call_args[0][0]
        self.assertIsNone(call_args["session_id"])
        self.assertIsNone(call_args["attachments"])

    def test_stream_with_step_messages(self):
        """Should correctly wrap step_start/step_complete SSE events."""
        lines = [
            json.dumps({"type": "stream_start", "messageId": "m1"}),
            json.dumps({"type": "step_start", "stepId": "s1", "stepName": "Processing input"}),
            json.dumps({"type": "step_complete", "stepId": "s1"}),
            json.dumps({"type": "step_start", "stepId": "s2", "stepName": "Thinking"}),
            json.dumps({"type": "step_complete", "stepId": "s2"}),
            json.dumps({"type": "stream_end", "messageId": "m1"}),
        ]
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream(lines))

        handler = ChatSSEHandler(engine=engine)
        events = _run(_collect(handler, {"content": "Hello"}))

        self.assertEqual(len(events), 6)
        # Verify each event is valid SSE format
        for event in events:
            self.assertTrue(event.startswith("data: "))
            self.assertTrue(event.endswith("\n\n"))
            # Verify the JSON inside is parseable
            json_str = event[6:-2]  # strip "data: " and "\n\n"
            parsed = json.loads(json_str)
            self.assertIsInstance(parsed, dict)

    def test_stream_with_a2ui_messages(self):
        """A2UI messages (with version field) should be wrapped as SSE events."""
        lines = [
            json.dumps({"type": "stream_start", "messageId": "m1"}),
            json.dumps({
                "version": "v0.10",
                "createSurface": {"surfaceId": "s-1", "catalogId": "openbench:v1"},
            }),
            json.dumps({
                "version": "v0.10",
                "updateComponents": {
                    "surfaceId": "s-1",
                    "components": [{"id": "root", "component": "Text", "text": "Hello"}],
                },
            }),
            json.dumps({"type": "stream_end", "messageId": "m1"}),
        ]
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream(lines))

        handler = ChatSSEHandler(engine=engine)
        events = _run(_collect(handler, {"content": "Hello"}))

        self.assertEqual(len(events), 4)
        # Check A2UI message is preserved
        a2ui_event = json.loads(events[1][6:-2])
        self.assertEqual(a2ui_event["version"], "v0.10")
        self.assertIn("createSurface", a2ui_event)

    def test_stream_empty_response(self):
        """Engine returning no lines should yield no events."""
        engine = MagicMock()
        engine.async_stream = MagicMock(return_value=MockAsyncStream([]))

        handler = ChatSSEHandler(engine=engine)
        events = _run(_collect(handler, {"content": "Hello"}))

        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
