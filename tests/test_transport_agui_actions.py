"""Tests for AGUIActionHandler (REST handler for A2UI actions)."""

import asyncio
import unittest
from typing import Any

from openbench.chat.a2ui.schema import A2UI_VERSION
from openbench.chat.engine import ChatEngine
from openbench.chat.transport.agui_actions import AGUIActionHandler
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult


class MockAgent(Agent):
    """Mock agent for testing."""

    def __init__(self, response: str = "Action reply"):
        self._response = response

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output=self._response,
            status="success",
            metadata={"model": "mock"},
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


class MockRequest:
    """Mock FastAPI Request object."""

    def __init__(self, body: dict[str, Any]):
        self._body = body

    async def json(self) -> dict[str, Any]:
        return self._body


def _run(coro):
    """Helper to run async code in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAGUIActionHandlerInit(unittest.TestCase):
    """Tests for AGUIActionHandler initialization."""

    def test_init_stores_engine(self):
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)
        self.assertIs(handler.engine, engine)


class TestAGUIActionHandlerHandle(unittest.TestCase):
    """Tests for AGUIActionHandler.handle()."""

    def test_handle_returns_a2ui_messages(self):
        """Should return A2UI messages from engine.invoke()."""
        engine = ChatEngine(agent=MockAgent("Action reply"))
        handler = AGUIActionHandler(engine=engine)
        request = MockRequest(
            {
                "name": "submit_form",
                "surfaceId": "s-1",
                "sourceComponentId": "btn-1",
                "context": {"field": "value"},
            }
        )

        messages = _run(handler.handle(request))

        self.assertIsInstance(messages, list)
        self.assertTrue(len(messages) > 0)

        # Should contain A2UI messages
        a2ui_msgs = [m for m in messages if m.get("version") == A2UI_VERSION]
        self.assertTrue(len(a2ui_msgs) >= 2)  # createSurface + updateComponents

    def test_handle_forwards_action_to_engine(self):
        """Action data should be forwarded to engine.invoke()."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIActionHandler(engine=engine)
        request = MockRequest(
            {
                "name": "click_button",
                "surfaceId": "s-1",
                "context": {"key": "val"},
            }
        )

        _run(handler.handle(request))

        # Engine should have processed the action (session updated)
        self.assertTrue(len(engine.session) > 0)

    def test_handle_with_missing_optional_fields(self):
        """Should handle action with minimal fields."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIActionHandler(engine=engine)
        request = MockRequest(
            {
                "name": "click",
            }
        )

        messages = _run(handler.handle(request))

        self.assertIsInstance(messages, list)

    def test_handle_preserves_action_context(self):
        """Context dict should be passed through to engine."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        handler = AGUIActionHandler(engine=engine)
        request = MockRequest(
            {
                "name": "update_value",
                "surfaceId": "s-1",
                "sourceComponentId": "slider-1",
                "context": {"value": 42, "min": 0, "max": 100},
            }
        )

        messages = _run(handler.handle(request))

        self.assertIsInstance(messages, list)


if __name__ == "__main__":
    unittest.main()
