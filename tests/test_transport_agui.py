"""Tests for AGUIHandler (AG-UI protocol transport)."""

import asyncio
import json
import unittest
from typing import Any

from openbench.chat.a2ui.schema import A2UI_VERSION
from openbench.chat.engine import ChatEngine
from openbench.chat.transport.agui import AGUIHandler
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult


class MockAgent(Agent):
    """Mock agent for testing."""

    def __init__(self, response: str = "Hello!"):
        self._response = response

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output=self._response,
            status="success",
            metadata={"model": "mock"},
            tokens_used=10,
            cost=0.001,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.001


class ErrorMockAgent(Agent):
    """Mock agent that raises an error."""

    @property
    def agent_type(self) -> str:
        return "error-mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        raise RuntimeError("Agent crashed")

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class MockRequest:
    """Mock FastAPI Request object."""

    def __init__(self, body: dict[str, Any], accept: str = "text/event-stream"):
        self._body = body
        self.headers = {"accept": accept}

    async def json(self) -> dict[str, Any]:
        return self._body


def _run(coro):
    """Helper to run async code in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect_events(handler: AGUIHandler, body: dict[str, Any]) -> list[dict]:
    """Collect all SSE events from handler._event_stream()."""
    events = []
    async for sse_line in handler._event_stream(body, "text/event-stream"):
        # Parse SSE: "data: {json}\n\n"
        line = sse_line.strip()
        if line.startswith("data: "):
            data = json.loads(line[6:])
            events.append(data)
    return events


class TestAGUIHandlerInit(unittest.TestCase):
    """Tests for AGUIHandler initialization."""

    def test_init_stores_engine(self):
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIHandler(engine=engine)
        self.assertIs(handler.engine, engine)


class TestAGUIHandlerEventStream(unittest.TestCase):
    """Tests for AGUIHandler._event_stream() -- AG-UI event generation."""

    def test_event_stream_starts_with_run_started(self):
        """First event should be RUN_STARTED."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        self.assertEqual(events[0]["type"], "RUN_STARTED")
        self.assertIn("threadId", events[0])
        self.assertIn("runId", events[0])

    def test_event_stream_ends_with_run_finished(self):
        """Last event should be RUN_FINISHED."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        self.assertIn("result", events[-1])

    def test_event_stream_three_step_pairs(self):
        """Should emit exactly 3 STEP_STARTED and 3 STEP_FINISHED events."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        step_starts = [e for e in events if e["type"] == "STEP_STARTED"]
        step_finishes = [e for e in events if e["type"] == "STEP_FINISHED"]

        self.assertEqual(len(step_starts), 3)
        self.assertEqual(len(step_finishes), 3)

    def test_event_stream_step_names(self):
        """Steps should have correct names in order."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        step_starts = [e for e in events if e["type"] == "STEP_STARTED"]
        names = [s["stepName"] for s in step_starts]

        self.assertEqual(names, ["Processing input", "Thinking", "Rendering response"])

    def test_event_stream_contains_a2ui_custom_events(self):
        """Should include CUSTOM events with name='a2ui' for A2UI messages."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        custom_events = [e for e in events if e["type"] == "CUSTOM" and e.get("name") == "a2ui"]
        self.assertTrue(len(custom_events) >= 2)

        # First A2UI message should be createSurface
        first_value = custom_events[0]["value"]
        self.assertEqual(first_value["version"], A2UI_VERSION)
        self.assertIn("createSurface", first_value)

        # Second should be updateComponents
        second_value = custom_events[1]["value"]
        self.assertIn("updateComponents", second_value)

    def test_event_stream_a2ui_between_rendering_steps(self):
        """CUSTOM(a2ui) events should appear between Rendering step_start and step_finish."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        rendering_start_idx = None
        rendering_finish_idx = None
        for i, e in enumerate(events):
            if e["type"] == "STEP_STARTED" and e.get("stepName") == "Rendering response":
                rendering_start_idx = i
            if (
                rendering_start_idx is not None
                and e["type"] == "STEP_FINISHED"
                and i > rendering_start_idx
                and rendering_finish_idx is None
            ):
                rendering_finish_idx = i

        self.assertIsNotNone(rendering_start_idx)
        self.assertIsNotNone(rendering_finish_idx)

        custom_indices = [
            i for i, e in enumerate(events) if e["type"] == "CUSTOM" and e.get("name") == "a2ui"
        ]
        for idx in custom_indices:
            self.assertGreater(idx, rendering_start_idx)
            self.assertLess(idx, rendering_finish_idx)

    def test_event_stream_run_finished_has_result(self):
        """RUN_FINISHED should include result with content and metadata."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        run_finished = events[-1]
        self.assertEqual(run_finished["type"], "RUN_FINISHED")
        result = run_finished["result"]
        self.assertIn("content", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["content"], "Reply")

    def test_event_stream_updates_session(self):
        """Session should have user + assistant messages after processing."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        _run(_collect_events(handler, {"content": "Hello"}))

        self.assertEqual(len(engine.session), 2)

    def test_event_stream_thread_id_from_body(self):
        """Should use threadId from body if provided."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello", "threadId": "my-thread"}))

        self.assertEqual(events[0]["threadId"], "my-thread")

    def test_event_stream_consistent_thread_and_run_ids(self):
        """RUN_STARTED and RUN_FINISHED should share the same threadId and runId."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        run_started = events[0]
        run_finished = events[-1]
        self.assertEqual(run_started["threadId"], run_finished["threadId"])
        self.assertEqual(run_started["runId"], run_finished["runId"])


class TestAGUIHandlerErrorHandling(unittest.TestCase):
    """Tests for error handling in AGUIHandler."""

    def test_error_sends_run_error_event(self):
        """Agent error should produce a RUN_ERROR event."""
        engine = ChatEngine(agent=ErrorMockAgent())
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        error_events = [e for e in events if e["type"] == "RUN_ERROR"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("message", error_events[0])
        self.assertEqual(error_events[0]["code"], "AGENT_ERROR")


class TestAGUIHandlerContentExtraction(unittest.TestCase):
    """Tests for _extract_content() -- dual format support."""

    def test_extract_openbench_format(self):
        """Should extract content from OpenBench format {content: '...'}."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIHandler(engine=engine)

        content, attachments = handler._extract_content({"content": "Hello"})

        self.assertEqual(content, "Hello")
        self.assertIsNone(attachments)

    def test_extract_agui_format_messages(self):
        """Should extract content from AG-UI format (messages array)."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIHandler(engine=engine)

        body = {
            "threadId": "t1",
            "runId": "r1",
            "messages": [
                {"id": "m1", "role": "user", "content": "First message"},
                {"id": "m2", "role": "assistant", "content": "Reply"},
                {"id": "m3", "role": "user", "content": "Follow up"},
            ],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }

        content, attachments = handler._extract_content(body)

        self.assertEqual(content, "Follow up")
        self.assertIsNone(attachments)

    def test_extract_agui_format_with_attachments(self):
        """Should extract attachments from forwardedProps."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIHandler(engine=engine)

        body = {
            "messages": [{"id": "m1", "role": "user", "content": "With file"}],
            "forwardedProps": {
                "attachments": [
                    {
                        "id": "a1",
                        "name": "doc.pdf",
                        "url": "/files/doc.pdf",
                        "type": "file",
                        "mimeType": "application/pdf",
                    }
                ],
            },
            "state": {},
            "tools": [],
            "context": [],
        }

        content, attachments = handler._extract_content(body)

        self.assertEqual(content, "With file")
        self.assertIsNotNone(attachments)
        self.assertEqual(len(attachments), 1)

    def test_extract_empty_content_defaults_to_empty_string(self):
        """Missing content should default to empty string."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIHandler(engine=engine)

        content, attachments = handler._extract_content({})

        self.assertEqual(content, "")
        self.assertIsNone(attachments)

    def test_extract_agui_format_no_user_messages(self):
        """Messages array with no user messages should return empty content."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIHandler(engine=engine)

        body = {
            "messages": [{"id": "m1", "role": "assistant", "content": "Hello"}],
            "forwardedProps": {},
            "state": {},
            "tools": [],
            "context": [],
        }

        content, attachments = handler._extract_content(body)

        self.assertEqual(content, "")


class TestAGUIHandlerHandle(unittest.TestCase):
    """Tests for handle() -- full request handling."""

    def test_handle_returns_streaming_response(self):
        """handle() should return a StreamingResponse."""
        from fastapi.responses import StreamingResponse

        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)
        request = MockRequest({"content": "Hello"})

        response = _run(handler.handle(request))

        self.assertIsInstance(response, StreamingResponse)
        self.assertEqual(response.media_type, "text/event-stream")


if __name__ == "__main__":
    unittest.main()
