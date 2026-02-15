"""Tests for AGUIActionHandler (REST handler for A2UI actions)."""

import asyncio
import unittest
from typing import Any
from unittest.mock import MagicMock

from openbench.chat.engine import ChatEngine
from openbench.chat.transport.agui_actions import ActionData, AGUIActionHandler
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult


class MockAgent(Agent):
    """Mock agent for testing."""

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(output="reply", status="success", metadata={})

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


class TestActionData(unittest.TestCase):
    """Tests for ActionData dataclass."""

    def test_defaults(self):
        action = ActionData(name="click", surface_id="s-1")
        self.assertEqual(action.name, "click")
        self.assertEqual(action.surface_id, "s-1")
        self.assertIsNone(action.source_component_id)
        self.assertEqual(action.context, {})

    def test_full_fields(self):
        action = ActionData(
            name="submit_form",
            surface_id="s-1",
            source_component_id="btn-1",
            context={"field": "value"},
        )
        self.assertEqual(action.source_component_id, "btn-1")
        self.assertEqual(action.context, {"field": "value"})


class TestAGUIActionHandlerInit(unittest.TestCase):
    """Tests for AGUIActionHandler initialization."""

    def test_init_stores_engine(self):
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)
        self.assertIs(handler.engine, engine)

    def test_init_empty_handlers(self):
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)
        self.assertEqual(handler._handlers, {})


class TestAGUIActionHandlerDefaultResponse(unittest.TestCase):
    """Tests for default response when no handler registered."""

    def test_default_response_returns_empty(self):
        """No registered handler -> returns empty list (no-op)."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)
        request = MockRequest({"name": "unknown_action", "surfaceId": "s-1", "context": {}})

        messages = _run(handler.handle(request))

        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 0)

    def test_action_data_with_missing_fields(self):
        """Minimal body handled gracefully -- returns empty (no-op)."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)
        request = MockRequest({"name": "click"})

        messages = _run(handler.handle(request))

        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 0)


class TestAGUIActionHandlerRegistry(unittest.TestCase):
    """Tests for handler registration and dispatch."""

    def test_registered_handler_called(self):
        """Custom handler called for matching action name."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)

        called_with = []

        @handler.on("submit_form")
        def handle_submit(action: ActionData):
            called_with.append(action)
            return [{"type": "updateComponents", "custom": True}]

        request = MockRequest(
            {
                "name": "submit_form",
                "surfaceId": "s-1",
                "sourceComponentId": "btn-1",
                "context": {"field": "value"},
            }
        )

        messages = _run(handler.handle(request))

        self.assertEqual(len(called_with), 1)
        self.assertEqual(called_with[0].name, "submit_form")
        self.assertEqual(called_with[0].surface_id, "s-1")
        self.assertEqual(called_with[0].source_component_id, "btn-1")
        self.assertEqual(called_with[0].context, {"field": "value"})
        self.assertEqual(messages, [{"type": "updateComponents", "custom": True}])

    def test_register_method(self):
        """register() method works like on() decorator."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)

        def my_handler(action: ActionData):
            return [{"handled": True}]

        handler.register("my_action", my_handler)

        request = MockRequest({"name": "my_action", "surfaceId": "s-1"})
        messages = _run(handler.handle(request))

        self.assertEqual(messages, [{"handled": True}])

    def test_async_handler_supported(self):
        """Async handlers are awaited properly."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)

        @handler.on("async_action")
        async def handle_async(action: ActionData):
            return [{"async": True, "surface": action.surface_id}]

        request = MockRequest({"name": "async_action", "surfaceId": "s-2"})
        messages = _run(handler.handle(request))

        self.assertEqual(messages, [{"async": True, "surface": "s-2"}])

    def test_handler_receives_action_data(self):
        """Handler receives correct ActionData fields."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)

        received = []

        @handler.on("test_action")
        def capture(action: ActionData):
            received.append(action)
            return []

        request = MockRequest(
            {
                "name": "test_action",
                "surfaceId": "surface-42",
                "sourceComponentId": "slider-1",
                "context": {"value": 42, "min": 0, "max": 100},
            }
        )

        _run(handler.handle(request))

        self.assertEqual(len(received), 1)
        action = received[0]
        self.assertIsInstance(action, ActionData)
        self.assertEqual(action.name, "test_action")
        self.assertEqual(action.surface_id, "surface-42")
        self.assertEqual(action.source_component_id, "slider-1")
        self.assertEqual(action.context, {"value": 42, "min": 0, "max": 100})

    def test_no_agent_execution(self):
        """Verify engine.invoke() is NOT called (key regression test)."""
        engine = ChatEngine(agent=MockAgent())
        engine.invoke = MagicMock(side_effect=AssertionError("invoke should not be called"))
        handler = AGUIActionHandler(engine=engine)

        @handler.on("submit_form")
        def handle_submit(action: ActionData):
            return [{"ok": True}]

        request = MockRequest(
            {"name": "submit_form", "surfaceId": "s-1", "context": {"data": "test"}}
        )

        # Should NOT raise -- engine.invoke() must not be called
        messages = _run(handler.handle(request))
        self.assertEqual(messages, [{"ok": True}])
        engine.invoke.assert_not_called()

    def test_no_agent_execution_default_handler(self):
        """Default handler also does NOT call engine.invoke()."""
        engine = ChatEngine(agent=MockAgent())
        engine.invoke = MagicMock(side_effect=AssertionError("invoke should not be called"))
        handler = AGUIActionHandler(engine=engine)

        request = MockRequest({"name": "unknown", "surfaceId": "s-1"})

        messages = _run(handler.handle(request))
        self.assertEqual(len(messages), 0)
        engine.invoke.assert_not_called()

    def test_on_decorator_returns_original_function(self):
        """on() decorator should not wrap the function."""
        engine = ChatEngine(agent=MockAgent())
        handler = AGUIActionHandler(engine=engine)

        @handler.on("test")
        def my_func(action: ActionData):
            return []

        self.assertIs(handler._handlers["test"], my_func)


if __name__ == "__main__":
    unittest.main()
