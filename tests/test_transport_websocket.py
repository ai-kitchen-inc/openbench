"""Tests for ChatWebSocketServer."""

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from openbench.chat.a2ui.schema import A2UI_VERSION
from openbench.chat.engine import ChatEngine
from openbench.chat.session import ChatSession
from openbench.chat.transport.websocket import ChatWebSocketServer
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


class SlowMockAgent(Agent):
    """Mock agent that simulates slow processing."""

    def __init__(self, response: str = "Slow reply", delay: float = 0.1):
        self._response = response
        self._delay = delay

    @property
    def agent_type(self) -> str:
        return "slow-mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        import time
        time.sleep(self._delay)
        return ExecutionResult(
            output=self._response, status="success", metadata={},
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class ErrorMockAgent(Agent):
    """Mock agent that raises an error."""

    @property
    def agent_type(self) -> str:
        return "error-mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        raise RuntimeError("Agent crashed")

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class MockWebSocket:
    """Mock FastAPI WebSocket for testing."""

    def __init__(self):
        self.accepted = False
        self.sent_messages: list[dict[str, Any]] = []
        self._receive_queue: list[str] = []
        self._closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict[str, Any]):
        self.sent_messages.append(data)

    async def receive_text(self) -> str:
        if not self._receive_queue:
            # Simulate disconnect
            raise Exception("WebSocket disconnected")
        return self._receive_queue.pop(0)

    def enqueue_message(self, data: dict[str, Any]):
        """Enqueue a message for the server to receive."""
        self._receive_queue.append(json.dumps(data))

    def enqueue_disconnect(self):
        """Enqueue a disconnect event (empty queue triggers exception)."""
        pass  # Default behavior when queue is empty


def _run(coro):
    """Helper to run async code in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestWebSocketServerInit(unittest.TestCase):
    """Tests for ChatWebSocketServer initialization."""

    def test_init_stores_engine(self):
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        self.assertIs(server.engine, engine)

    def test_init_empty_sessions(self):
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        self.assertEqual(server._sessions, {})


class TestWebSocketServerSendReceive(unittest.TestCase):
    """Tests for send() and receive() methods."""

    def test_send_calls_websocket_send_json(self):
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server.send(ws, {"type": "test", "data": 42}))

        self.assertEqual(len(ws.sent_messages), 1)
        self.assertEqual(ws.sent_messages[0], {"type": "test", "data": 42})

    def test_receive_parses_json(self):
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()
        ws.enqueue_message({"type": "message", "content": "Hello"})

        result = _run(server.receive(ws))

        self.assertEqual(result, {"type": "message", "content": "Hello"})


class TestWebSocketServerSendFlush(unittest.TestCase):
    """Tests for _send_flush() method."""

    def test_send_flush_sends_data(self):
        """_send_flush should send the data via WebSocket."""
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._send_flush(ws, {"type": "test"}))

        self.assertEqual(len(ws.sent_messages), 1)
        self.assertEqual(ws.sent_messages[0], {"type": "test"})

    def test_send_flush_yields_event_loop(self):
        """_send_flush should call asyncio.sleep(0) to yield to event loop."""
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        with patch("openbench.chat.transport.websocket.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            _run(server._send_flush(ws, {"type": "test"}))
            mock_sleep.assert_called_once_with(0)


class TestWebSocketServerProcessMessage(unittest.TestCase):
    """Tests for _process_message() -- main orchestration method."""

    def test_process_message_sends_stream_start(self):
        """First message should be stream_start."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        self.assertEqual(ws.sent_messages[0]["type"], "stream_start")
        self.assertIn("messageId", ws.sent_messages[0])

    def test_process_message_sends_stream_end(self):
        """Last message should be stream_end."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        self.assertEqual(ws.sent_messages[-1]["type"], "stream_end")

    def test_process_message_three_step_pairs(self):
        """Should emit exactly 3 step_start and 3 step_complete messages."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        step_starts = [m for m in ws.sent_messages if m.get("type") == "step_start"]
        step_completes = [m for m in ws.sent_messages if m.get("type") == "step_complete"]

        self.assertEqual(len(step_starts), 3)
        self.assertEqual(len(step_completes), 3)

    def test_process_message_step_names(self):
        """Steps should have correct names in order."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        step_starts = [m for m in ws.sent_messages if m.get("type") == "step_start"]
        names = [s["stepName"] for s in step_starts]

        self.assertEqual(names, ["Processing input", "Thinking", "Rendering response"])

    def test_process_message_unique_step_ids(self):
        """Each step should have a unique stepId."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        step_starts = [m for m in ws.sent_messages if m.get("type") == "step_start"]
        step_ids = [s["stepId"] for s in step_starts]

        self.assertEqual(len(step_ids), len(set(step_ids)))

    def test_process_message_contains_a2ui_messages(self):
        """Should include A2UI messages (createSurface + updateComponents)."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        a2ui_msgs = [m for m in ws.sent_messages if m.get("version") == A2UI_VERSION]
        self.assertTrue(len(a2ui_msgs) >= 2)

        # First A2UI message should be createSurface
        self.assertIn("createSurface", a2ui_msgs[0])
        # Second should be updateComponents
        self.assertIn("updateComponents", a2ui_msgs[1])

    def test_process_message_a2ui_between_rendering_steps(self):
        """A2UI messages should appear between rendering step_start and step_complete."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        # Find rendering step boundaries
        rendering_start_idx = None
        rendering_complete_idx = None
        for i, m in enumerate(ws.sent_messages):
            if m.get("type") == "step_start" and m.get("stepName") == "Rendering response":
                rendering_start_idx = i
            if rendering_start_idx is not None and m.get("type") == "step_complete" and i > rendering_start_idx:
                if rendering_complete_idx is None:
                    rendering_complete_idx = i

        self.assertIsNotNone(rendering_start_idx)
        self.assertIsNotNone(rendering_complete_idx)

        a2ui_indices = [i for i, m in enumerate(ws.sent_messages) if m.get("version") == A2UI_VERSION]
        for idx in a2ui_indices:
            self.assertGreater(idx, rendering_start_idx)
            self.assertLess(idx, rendering_complete_idx)

    def test_process_message_message_id_consistency(self):
        """All step and stream messages should share the same messageId."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        stream_start = ws.sent_messages[0]
        message_id = stream_start["messageId"]

        envelope_msgs = [
            m for m in ws.sent_messages
            if m.get("type") in ("stream_start", "stream_end", "step_start", "step_complete")
        ]
        for msg in envelope_msgs:
            self.assertEqual(msg.get("messageId"), message_id)

    def test_process_message_updates_session(self):
        """Session should have user + assistant messages after processing."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        self.assertEqual(len(engine.session), 2)

    def test_process_message_tracks_session_id(self):
        """Connection should be mapped to session ID."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello", "sessionId": "sess-42"}, "conn-1",
        ))

        self.assertEqual(server._sessions.get("conn-1"), "sess-42")

    def test_process_message_error_sends_error_message(self):
        """Agent error should produce an error envelope message."""
        engine = ChatEngine(agent=ErrorMockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Hello"}, "conn-1",
        ))

        # Should have stream_start, then some steps, then error
        error_msgs = [m for m in ws.sent_messages if m.get("type") == "error"]
        self.assertEqual(len(error_msgs), 1)
        self.assertIn("error", error_msgs[0].get("metadata", {}))

    def test_process_message_with_slow_agent(self):
        """Should handle agent call via asyncio.to_thread without blocking."""
        engine = ChatEngine(agent=SlowMockAgent("Delayed", delay=0.05))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        _run(server._process_message(
            ws, {"content": "Wait"}, "conn-1",
        ))

        # Should complete with all messages including stream_end
        types = [m.get("type") for m in ws.sent_messages]
        self.assertIn("stream_start", types)
        self.assertIn("stream_end", types)


class TestWebSocketServerHandleAction(unittest.TestCase):
    """Tests for _handle_action() method."""

    def test_handle_action_calls_engine_invoke(self):
        """Action should be forwarded to engine.invoke()."""
        engine = ChatEngine(agent=MockAgent("Action reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        action_data = {
            "type": "action",
            "name": "submit_form",
            "surfaceId": "s-1",
            "sourceComponentId": "btn-1",
            "context": {"field": "value"},
        }

        _run(server._handle_action(ws, action_data))

        # Engine should have processed the action (session updated)
        self.assertTrue(len(engine.session) > 0)

    def test_handle_action_sends_response_messages(self):
        """Action response messages should be sent to client."""
        engine = ChatEngine(agent=MockAgent("Action reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        action_data = {
            "type": "action",
            "name": "click",
            "surfaceId": "s-1",
            "context": {},
        }

        _run(server._handle_action(ws, action_data))

        # Should have sent response messages (A2UI)
        self.assertTrue(len(ws.sent_messages) > 0)

    def test_handle_action_error_sends_error_message(self):
        """Error during action handling should send error message."""
        engine = ChatEngine(agent=ErrorMockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()

        action_data = {
            "type": "action",
            "name": "click",
            "surfaceId": "s-1",
            "context": {},
        }

        _run(server._handle_action(ws, action_data))

        error_msgs = [m for m in ws.sent_messages if m.get("type") == "error"]
        self.assertEqual(len(error_msgs), 1)


class TestWebSocketServerHandle(unittest.TestCase):
    """Tests for handle() -- connection lifecycle."""

    def test_handle_accepts_connection(self):
        """Should call websocket.accept() on connection."""
        engine = ChatEngine(agent=MockAgent())
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()
        # No messages enqueued → immediate disconnect

        _run(server.handle(ws))

        self.assertTrue(ws.accepted)

    def test_handle_routes_message_type(self):
        """Should route 'message' type to _process_message."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()
        ws.enqueue_message({"type": "message", "content": "Hello"})

        _run(server.handle(ws))

        # Should have processed the message (stream_start present)
        types = [m.get("type") for m in ws.sent_messages]
        self.assertIn("stream_start", types)

    def test_handle_cleans_up_session_on_disconnect(self):
        """Session mapping should be cleaned on disconnect."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        server = ChatWebSocketServer(engine=engine)
        ws = MockWebSocket()
        ws.enqueue_message({"type": "message", "content": "Hi", "sessionId": "sess-1"})

        _run(server.handle(ws))

        # After disconnect, connection should be removed from sessions
        self.assertEqual(len(server._sessions), 0)


if __name__ == "__main__":
    unittest.main()
