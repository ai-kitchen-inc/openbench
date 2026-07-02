"""Tests for AGUIHandler (AG-UI protocol transport)."""

import asyncio
import json
import unittest
from typing import Any

from fastapi import HTTPException

from openbench.chat.a2ui.schema import A2UI_VERSION
from openbench.chat.engine import ChatEngine
from openbench.chat.transport.agui import A2UIStreamMessage, AGUIHandler
from openbench.chat.transport.validation import MAX_CONTENT_LENGTH
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult
from openbench.mcp.permissions import (
    MCPPermissionContext,
    MCPPermissionRequest,
    MCPPermissionSession,
)
from openbench.mcp.policy import RiskLevel


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


class StreamingMockAgent(Agent):
    """Mock agent that supports on_chunk streaming callback."""

    def __init__(self, chunks: list[str] | None = None):
        self._chunks = chunks or ["Hello", " ", "World", "!"]

    @property
    def agent_type(self) -> str:
        return "streaming-mock"

    def execute(self, context: ExecutionContext, on_chunk=None) -> ExecutionResult:
        full_text = ""
        for chunk in self._chunks:
            if on_chunk:
                on_chunk(chunk)
            full_text += chunk
        return ExecutionResult(
            output=full_text,
            status="success",
            metadata={"model": "mock"},
            tokens_used=10,
            cost=0.001,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.001


class CountingAgent(MockAgent):
    """Mock agent that records whether execution was reached."""

    def __init__(self, response: str = "Hello!"):
        super().__init__(response)
        self.calls = 0

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        self.calls += 1
        return super().execute(context)


class PermissionPromptAgent(Agent):
    """Mock agent that requests MCP permission during execution."""

    @property
    def agent_type(self) -> str:
        return "permission-prompt-mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        request = MCPPermissionRequest(
            tool_name="openbench.distinct_values",
            purpose="Distinct values",
            arguments={"column": "region"},
            risk=RiskLevel.READ,
            action="Call MCP tool.",
        )
        decision = MCPPermissionSession().request(request)
        return ExecutionResult(
            output="approved" if decision.approved else "blocked",
            status="success",
            metadata={},
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class PermissionPromptHandler(AGUIHandler):
    def _create_permission_context(self, *, session_id, thread_id, run_id, queue, loop):
        def provider(_request):
            loop.call_soon_threadsafe(
                queue.put_nowait,
                A2UIStreamMessage(
                    {
                        "version": A2UI_VERSION,
                        "createSurface": {
                            "surfaceId": "permission-surface",
                            "catalogId": "openbench",
                        },
                    }
                ),
            )
            return "yes"

        return MCPPermissionContext(provider)


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

    def __init__(self, body: Any, accept: str = "text/event-stream"):
        self._body = body
        self.headers = {"accept": accept}

    async def json(self) -> Any:
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


async def _collect_response_events(response: Any) -> list[dict]:
    """Collect all SSE events from a StreamingResponse."""
    events = []
    async for chunk in response.body_iterator:
        line = chunk.decode() if isinstance(chunk, bytes) else chunk
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
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

    def test_event_stream_text_only_has_one_step_pair_for_non_base_agent(self):
        """Non-BaseAgent text-only response emits 1 STEP pair (Processing input only).

        BaseAgent emits ProgressEvents that produce dynamic sub-steps.
        Non-BaseAgent agents don't emit progress, so no Thinking step appears.
        """
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        step_starts = [e for e in events if e["type"] == "STEP_STARTED"]
        step_finishes = [e for e in events if e["type"] == "STEP_FINISHED"]

        self.assertEqual(len(step_starts), 1)
        self.assertEqual(len(step_finishes), 1)

    def test_event_stream_text_only_step_names(self):
        """Non-BaseAgent text-only steps should only have Processing input."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        step_starts = [e for e in events if e["type"] == "STEP_STARTED"]
        names = [s["stepName"] for s in step_starts]

        self.assertEqual(names, ["Processing input"])

    def test_event_stream_text_only_no_a2ui_events(self):
        """Text-only response should NOT emit A2UI surface events."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        custom_events = [e for e in events if e["type"] == "CUSTOM" and e.get("name") == "a2ui"]
        self.assertEqual(len(custom_events), 0)

    def test_event_stream_emits_mid_run_a2ui_message(self):
        """A2UI stream messages should emit as CUSTOM events during a run."""
        engine = ChatEngine(agent=PermissionPromptAgent())
        handler = PermissionPromptHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Use a tool"}))

        custom_events = [
            event
            for event in events
            if event.get("type") == "CUSTOM" and event.get("name") == "a2ui"
        ]
        self.assertEqual(len(custom_events), 1)
        self.assertEqual(
            custom_events[0]["value"]["createSurface"]["surfaceId"],
            "permission-surface",
        )
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        self.assertEqual(events[-1]["result"]["content"], "approved")

    def test_event_stream_rich_content_has_two_step_pairs_for_non_base_agent(self):
        """Non-BaseAgent with rich content emits 2 STEP pairs (Processing + Rendering).

        No Thinking step since non-BaseAgent doesn't emit ProgressEvents.
        """
        chart_data = {
            "title": "Sales",
            "data": [{"x": "Q1", "y": 100}],
            "chart_type": "bar",
        }
        engine = ChatEngine(
            agent=MockAgent("Here are the results"),
            render_items_fn=lambda: [chart_data],
        )
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Show chart"}))

        step_starts = [e for e in events if e["type"] == "STEP_STARTED"]
        step_finishes = [e for e in events if e["type"] == "STEP_FINISHED"]

        self.assertEqual(len(step_starts), 2)
        self.assertEqual(len(step_finishes), 2)

    def test_event_stream_rich_content_has_a2ui_events(self):
        """Response with rich content should emit A2UI surface events."""
        chart_data = {
            "title": "Sales",
            "data": [{"x": "Q1", "y": 100}],
            "chart_type": "bar",
        }
        engine = ChatEngine(
            agent=MockAgent("Here are the results"),
            render_items_fn=lambda: [chart_data],
        )
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Show chart"}))

        custom_events = [e for e in events if e["type"] == "CUSTOM" and e.get("name") == "a2ui"]
        self.assertTrue(len(custom_events) >= 2)

        first_value = custom_events[0]["value"]
        self.assertEqual(first_value["version"], A2UI_VERSION)
        self.assertIn("createSurface", first_value)

    def test_event_stream_rich_content_a2ui_between_rendering_steps(self):
        """CUSTOM(a2ui) events should appear between Rendering step_start and step_finish."""
        chart_data = {
            "title": "Sales",
            "data": [{"x": "Q1", "y": 100}],
            "chart_type": "bar",
        }
        engine = ChatEngine(
            agent=MockAgent("Here are the results"),
            render_items_fn=lambda: [chart_data],
        )
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Show chart"}))

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
        """Per-session ChatSession should have user + assistant messages after processing."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        body = {
            "content": "Hello",
            "threadId": "test-thread",
            "forwardedProps": {"sessionId": "session-abc"},
        }
        _run(_collect_events(handler, body))

        # Session stored in handler's per-session dict, not engine.session
        session = handler._sessions.get("session-abc")
        self.assertIsNotNone(session)
        self.assertEqual(len(session), 2)

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

    def test_error_writes_aborted_placeholder(self):
        """Layer 2b — agent crash must leave an 'aborted' placeholder
        assistant message in the session + persistent store, so a
        reloaded thread doesn't dead-end on a bare user turn."""
        import tempfile
        from pathlib import Path

        from openbench.chat.stores.sqlite import SQLiteSessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionStore(str(Path(tmpdir) / "sessions.db"))
            engine = ChatEngine(agent=ErrorMockAgent(), session_store=store)
            handler = AGUIHandler(engine=engine)

            events = _run(
                _collect_events(
                    handler,
                    {"threadId": "thread-err-1", "content": "Hello"},
                )
            )

            # Error event emitted
            self.assertTrue(any(e["type"] == "RUN_ERROR" for e in events))

            # Session reloaded from store ends on aborted placeholder
            reloaded = store.load("thread-err-1")
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(len(reloaded.messages), 2)
            self.assertEqual(reloaded.messages[0].content, "Hello")
            last = reloaded.messages[1]
            self.assertIn("Turn interrupted", last.content)
            self.assertTrue(last.metadata.get("aborted"))
            self.assertIn("Agent crashed", last.metadata.get("error", ""))


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

        content, _attachments = handler._extract_content(body)

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

    def test_handle_valid_agui_messages_streams_normally(self):
        """A valid AG-UI messages body should pass validation and stream."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)
        request = MockRequest(
            {
                "threadId": "thread-1",
                "runId": "run-1",
                "messages": [{"role": "user", "content": "Hello"}],
                "forwardedProps": {"sessionId": "session-1"},
            }
        )

        response = _run(handler.handle(request))
        events = _run(_collect_response_events(response))

        self.assertEqual(events[0]["type"], "RUN_STARTED")
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        self.assertEqual(events[-1]["result"]["content"], "Reply")

    def test_handle_rejects_non_object_json_before_agent_execution(self):
        agent = CountingAgent("Reply")
        engine = ChatEngine(agent=agent)
        handler = AGUIHandler(engine=engine)

        with self.assertRaises(HTTPException) as ctx:
            _run(handler.handle(MockRequest(["not", "an", "object"])))

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(agent.calls, 0)
        self.assertEqual(handler._sessions, {})

    def test_handle_rejects_invalid_thread_id_before_agent_execution(self):
        agent = CountingAgent("Reply")
        engine = ChatEngine(agent=agent)
        handler = AGUIHandler(engine=engine)

        with self.assertRaises(HTTPException) as ctx:
            _run(handler.handle(MockRequest({"content": "Hello", "threadId": "bad id!"})))

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(agent.calls, 0)

    def test_handle_rejects_invalid_forwarded_session_id(self):
        agent = CountingAgent("Reply")
        engine = ChatEngine(agent=agent)
        handler = AGUIHandler(engine=engine)

        with self.assertRaises(HTTPException) as ctx:
            _run(
                handler.handle(
                    MockRequest(
                        {
                            "content": "Hello",
                            "forwardedProps": {"sessionId": "bad/session"},
                        }
                    )
                )
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(agent.calls, 0)

    def test_handle_rejects_overlong_content(self):
        agent = CountingAgent("Reply")
        engine = ChatEngine(agent=agent)
        handler = AGUIHandler(engine=engine)

        with self.assertRaises(HTTPException) as ctx:
            _run(handler.handle(MockRequest({"content": "x" * (MAX_CONTENT_LENGTH + 1)})))

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(agent.calls, 0)

    def test_handle_rejects_malformed_messages(self):
        agent = CountingAgent("Reply")
        engine = ChatEngine(agent=agent)
        handler = AGUIHandler(engine=engine)

        with self.assertRaises(HTTPException) as ctx:
            _run(handler.handle(MockRequest({"messages": [{"role": "user", "content": 123}]})))

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(agent.calls, 0)


class TestAGUIHandlerTextStreaming(unittest.TestCase):
    """Tests for progressive text streaming via TEXT_MESSAGE events."""

    def test_streaming_agent_emits_text_message_events(self):
        """Streaming agent should produce TEXT_MESSAGE_START/CONTENT/END events."""
        engine = ChatEngine(agent=StreamingMockAgent(["The ", "answer ", "is 42."]))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        types = [e["type"] for e in events]
        self.assertIn("TEXT_MESSAGE_START", types)
        self.assertIn("TEXT_MESSAGE_CONTENT", types)
        self.assertIn("TEXT_MESSAGE_END", types)

    def test_streaming_text_deltas_match_chunks(self):
        """TEXT_MESSAGE_CONTENT deltas should match the agent's chunks."""
        chunks = ["Solar ", "energy ", "costs ", "less."]
        engine = ChatEngine(agent=StreamingMockAgent(chunks))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Compare energy"}))

        content_events = [e for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"]
        deltas = [e["delta"] for e in content_events]

        self.assertEqual(deltas, chunks)

    def test_streaming_message_id_consistent(self):
        """TEXT_MESSAGE_START/CONTENT/END should share the same messageId."""
        engine = ChatEngine(agent=StreamingMockAgent(["a", "b"]))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        start_events = [e for e in events if e["type"] == "TEXT_MESSAGE_START"]
        content_events = [e for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"]
        end_events = [e for e in events if e["type"] == "TEXT_MESSAGE_END"]

        self.assertEqual(len(start_events), 1)
        self.assertEqual(len(end_events), 1)

        msg_id = start_events[0]["messageId"]
        for e in content_events:
            self.assertEqual(e["messageId"], msg_id)
        self.assertEqual(end_events[0]["messageId"], msg_id)

    def test_streaming_text_events_after_processing_input(self):
        """Text streaming events should appear after Processing input step.

        Non-BaseAgent agents don't emit ProgressEvents, so there's no Thinking
        step. Text events are emitted directly after the Processing input step.
        """
        engine = ChatEngine(agent=StreamingMockAgent(["x"]))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        processing_finish_idx = None
        for i, e in enumerate(events):
            if e["type"] == "STEP_FINISHED" and e.get("stepName") == "Processing input":
                processing_finish_idx = i

        self.assertIsNotNone(processing_finish_idx)

        text_indices = [
            i
            for i, e in enumerate(events)
            if e["type"] in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END")
        ]
        for idx in text_indices:
            self.assertGreater(idx, processing_finish_idx)

    def test_non_streaming_agent_still_emits_text_events(self):
        """Non-streaming MockAgent should still emit text events."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        types = [e["type"] for e in events]
        # Should still have TEXT_MESSAGE_START and TEXT_MESSAGE_END
        self.assertIn("TEXT_MESSAGE_START", types)
        self.assertIn("TEXT_MESSAGE_END", types)
        # Text-only: no A2UI events (text already streamed)
        custom_events = [e for e in events if e["type"] == "CUSTOM" and e.get("name") == "a2ui"]
        self.assertEqual(len(custom_events), 0)

    def test_streaming_with_rich_content_has_a2ui_events(self):
        """After streaming text, A2UI surface events emitted when rich content exists."""
        chart_data = {
            "title": "Sales",
            "data": [{"x": "Q1", "y": 100}],
            "chart_type": "bar",
        }
        engine = ChatEngine(
            agent=StreamingMockAgent(["Hello ", "world"]),
            render_items_fn=lambda: [chart_data],
        )
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Hello"}))

        custom_events = [e for e in events if e["type"] == "CUSTOM" and e.get("name") == "a2ui"]
        self.assertTrue(len(custom_events) >= 2)

        # Verify createSurface and updateComponents
        self.assertIn("createSurface", custom_events[0]["value"])
        self.assertIn("updateComponents", custom_events[1]["value"])

    def test_streaming_run_finished_has_full_content(self):
        """RUN_FINISHED result should have complete text, not just last delta."""
        chunks = ["Hello", " ", "World"]
        engine = ChatEngine(agent=StreamingMockAgent(chunks))
        handler = AGUIHandler(engine=engine)

        events = _run(_collect_events(handler, {"content": "Test"}))

        run_finished = [e for e in events if e["type"] == "RUN_FINISHED"]
        self.assertEqual(len(run_finished), 1)
        self.assertEqual(run_finished[0]["result"]["content"], "Hello World")


class TestAGUIHandlerSessionIsolation(unittest.TestCase):
    """Tests for per-session isolation in AGUIHandler."""

    def test_different_session_ids_get_separate_sessions(self):
        """Requests with different sessionIds should use separate ChatSession instances."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        body_a = {
            "content": "Hello from A",
            "forwardedProps": {"sessionId": "session-A"},
        }
        body_b = {
            "content": "Hello from B",
            "forwardedProps": {"sessionId": "session-B"},
        }

        _run(_collect_events(handler, body_a))
        _run(_collect_events(handler, body_b))

        # Each session should have exactly 2 messages (user + assistant)
        session_a = handler._sessions.get("session-A")
        session_b = handler._sessions.get("session-B")
        self.assertIsNotNone(session_a)
        self.assertIsNotNone(session_b)
        self.assertEqual(len(session_a), 2)
        self.assertEqual(len(session_b), 2)
        self.assertIsNot(session_a, session_b)

    def test_same_session_id_accumulates_messages(self):
        """Multiple requests with the same sessionId should accumulate in one session."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        body = {
            "content": "First message",
            "forwardedProps": {"sessionId": "session-shared"},
        }
        _run(_collect_events(handler, body))

        body["content"] = "Second message"
        _run(_collect_events(handler, body))

        session = handler._sessions.get("session-shared")
        self.assertIsNotNone(session)
        # 2 user + 2 assistant = 4 messages
        self.assertEqual(len(session), 4)

    def test_engine_session_not_modified(self):
        """Engine's default session should NOT be modified by AGUIHandler requests."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        initial_count = len(engine.session)

        body = {
            "content": "Hello",
            "forwardedProps": {"sessionId": "session-isolated"},
        }
        _run(_collect_events(handler, body))

        # Engine's session should remain untouched
        self.assertEqual(len(engine.session), initial_count)

    def test_session_id_fallback_to_thread_id(self):
        """When no sessionId in forwardedProps, should fall back to threadId."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        body = {"content": "Hello", "threadId": "my-thread-id"}
        _run(_collect_events(handler, body))

        session = handler._sessions.get("my-thread-id")
        self.assertIsNotNone(session)
        self.assertEqual(len(session), 2)

    def test_session_isolation_prevents_context_contamination(self):
        """Messages from one session should NOT appear in another session's context."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIHandler(engine=engine)

        body_a = {
            "content": "Topic A: quantum computing",
            "forwardedProps": {"sessionId": "session-A"},
        }
        body_b = {
            "content": "Topic B: cooking recipes",
            "forwardedProps": {"sessionId": "session-B"},
        }

        _run(_collect_events(handler, body_a))
        _run(_collect_events(handler, body_b))

        session_a = handler._sessions["session-A"]
        session_b = handler._sessions["session-B"]

        # Session A should only contain its own messages
        a_contents = [m.content for m in session_a.messages]
        self.assertTrue(any("quantum" in c for c in a_contents))
        self.assertFalse(any("cooking" in c for c in a_contents))

        # Session B should only contain its own messages
        b_contents = [m.content for m in session_b.messages]
        self.assertTrue(any("cooking" in c for c in b_contents))
        self.assertFalse(any("quantum" in c for c in b_contents))


class TestAGUIHandlerSessionPersistence(unittest.TestCase):
    """The handler must save to + load from the engine's session_store.

    Regression: a previous implementation maintained an in-memory
    ``_sessions`` dict that bypassed the store entirely, so Drive/SQLite
    backends silently did no persistence.
    """

    def _make_store(self):
        """Minimal in-memory SessionStore that records every call."""
        from openbench.chat.session_store import SessionStore

        class _MemStore(SessionStore):
            def __init__(self):
                self.saved: list[Any] = []
                self.loaded: list[str] = []
                self._db: dict[str, Any] = {}
                self.load_error: Exception | None = None

            def save(self, session):
                self.saved.append(session)
                self._db[session.session_id] = session

            def load(self, session_id):
                self.loaded.append(session_id)
                if self.load_error is not None:
                    raise self.load_error
                return self._db.get(session_id)

            def list(self, limit=50, offset=0):
                return []

            def delete(self, session_id):
                pass

        return _MemStore()

    def test_save_called_after_user_and_assistant_message(self):
        store = self._make_store()
        engine = ChatEngine(agent=MockAgent(response="hi"), session_store=store)
        handler = AGUIHandler(engine=engine)

        body = {
            "content": "hello",
            "forwardedProps": {"sessionId": "s-1"},
        }
        _run(_collect_events(handler, body))

        # Two saves per turn: one after user append, one after assistant.
        self.assertGreaterEqual(len(store.saved), 2)
        # Both saves point at the same session id.
        for saved in store.saved:
            self.assertEqual(saved.session_id, "s-1")
        # Final save includes both messages.
        final = store.saved[-1]
        roles = [str(m.role.value) for m in final.messages]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_load_consulted_before_in_memory_fallback(self):
        store = self._make_store()
        # Pre-seed the store with existing history for "s-1".
        from openbench.chat.session import ChatMessage, ChatSession

        seeded = ChatSession(session_id="s-1")
        seeded.messages.append(
            ChatMessage(id="m-old", role="user", content="earlier", timestamp="2026-01-01T00:00:00")
        )
        store._db["s-1"] = seeded

        engine = ChatEngine(agent=MockAgent(response="hi"), session_store=store)
        handler = AGUIHandler(engine=engine)

        body = {"content": "new message", "forwardedProps": {"sessionId": "s-1"}}
        _run(_collect_events(handler, body))

        self.assertIn("s-1", store.loaded)
        # Fresh session in handler's dict should carry the pre-seeded turn.
        self.assertEqual(handler._sessions["s-1"].session_id, "s-1")
        contents = [m.content for m in handler._sessions["s-1"].messages]
        self.assertIn("earlier", contents)
        self.assertIn("new message", contents)

    def test_load_failure_falls_back_to_in_memory_and_keeps_going(self):
        store = self._make_store()
        store.load_error = RuntimeError("drive offline")
        engine = ChatEngine(agent=MockAgent(), session_store=store)
        handler = AGUIHandler(engine=engine)

        body = {"content": "ping", "forwardedProps": {"sessionId": "s-err"}}
        # Must not raise despite load failure.
        events = _run(_collect_events(handler, body))
        self.assertTrue(any(e.get("type") == "RUN_FINISHED" for e in events))
        # Subsequent save is still attempted.
        self.assertGreaterEqual(len(store.saved), 1)

    def test_no_store_wired_is_a_no_op(self):
        """engine.session_store = None → handler must not crash."""
        engine = ChatEngine(agent=MockAgent())
        self.assertIsNone(engine.session_store)
        handler = AGUIHandler(engine=engine)

        body = {"content": "ping", "forwardedProps": {"sessionId": "s-none"}}
        events = _run(_collect_events(handler, body))
        self.assertTrue(any(e.get("type") == "RUN_FINISHED" for e in events))

    def test_on_session_resolved_hook_fires_once_per_request(self):
        """Subclasses use this hook to set up per-request thread-local state."""

        class _Recording(AGUIHandler):
            def __init__(self, engine):
                super().__init__(engine)
                self.hook_calls: list[str] = []

            def _on_session_resolved(self, session_id: str) -> None:
                self.hook_calls.append(session_id)

        engine = ChatEngine(agent=MockAgent())
        handler = _Recording(engine)

        body = {"content": "ping", "forwardedProps": {"sessionId": "abc"}}
        _run(_collect_events(handler, body))
        self.assertEqual(handler.hook_calls, ["abc"])

    def test_hook_fires_when_session_loaded_from_store(self):
        """Regression: hook must fire even on the load-from-store fast path."""
        store = self._make_store()
        from openbench.chat.session import ChatSession

        store._db["loaded-id"] = ChatSession(session_id="loaded-id")

        class _Recording(AGUIHandler):
            def __init__(self, engine):
                super().__init__(engine)
                self.hook_calls: list[str] = []

            def _on_session_resolved(self, session_id: str) -> None:
                self.hook_calls.append(session_id)

        engine = ChatEngine(agent=MockAgent(), session_store=store)
        handler = _Recording(engine)

        body = {"content": "ping", "forwardedProps": {"sessionId": "loaded-id"}}
        _run(_collect_events(handler, body))
        self.assertEqual(handler.hook_calls, ["loaded-id"])


if __name__ == "__main__":
    unittest.main()
