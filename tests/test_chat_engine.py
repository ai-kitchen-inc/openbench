"""Tests for ChatEngine."""

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import MagicMock

from openbench.chat.a2ui.schema import A2UI_VERSION
from openbench.chat.engine import ChatEngine
from openbench.chat.session import ChatSession, MessageRole
from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
    FrameworkAdapter,
)


class MockAgent(Agent):
    """Mock agent for testing ChatEngine."""

    def __init__(self, response: str = "Hello from agent!"):
        self._response = response

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output=self._response,
            status="success",
            metadata={"model": "mock-model"},
            tokens_used=42,
            cost=0.001,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.001


class MockFrameworkAdapter(FrameworkAdapter):
    """Mock framework adapter for testing."""

    def __init__(self, response: str = "Hello from adapter!"):
        self._response = response

    @property
    def framework_name(self) -> str:
        return "mock"

    def invoke(self, input: Any, config: Any | None = None) -> str:
        return self._response


class TestChatEngineInit(unittest.TestCase):
    """Tests for ChatEngine initialization."""

    def test_init_with_agent(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        self.assertIsNotNone(engine.session)
        self.assertIsNotNone(engine.builder)
        self.assertTrue(len(engine.renderers) > 0)

    def test_init_with_session(self):
        agent = MockAgent()
        session = ChatSession(session_id="test-session")
        engine = ChatEngine(agent=agent, session=session)
        self.assertEqual(engine.session.session_id, "test-session")

    def test_init_with_custom_catalog(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent, catalog_id="custom:v1")
        self.assertEqual(engine.builder.catalog_id, "custom:v1")


class TestChatEngineInvoke(unittest.TestCase):
    """Tests for ChatEngine.invoke()."""

    def test_invoke_string_input(self):
        engine = ChatEngine(agent=MockAgent("Hello!"))
        result = engine.invoke("Hi there")

        self.assertIn("messages", result)
        self.assertIn("session", result)
        self.assertIn("metadata", result)

    def test_invoke_dict_input(self):
        engine = ChatEngine(agent=MockAgent("Reply"))
        result = engine.invoke({"content": "Hello"})

        self.assertIn("messages", result)
        messages = result["messages"]
        self.assertTrue(len(messages) >= 2)  # createSurface + updateComponents

    def test_invoke_produces_valid_a2ui(self):
        engine = ChatEngine(agent=MockAgent("Test response"))
        result = engine.invoke({"content": "Test"})

        messages = result["messages"]
        # First message: createSurface
        self.assertEqual(messages[0]["version"], A2UI_VERSION)
        self.assertIn("createSurface", messages[0])

        # Second message: updateComponents
        self.assertEqual(messages[1]["version"], A2UI_VERSION)
        self.assertIn("updateComponents", messages[1])

    def test_invoke_has_root_component(self):
        engine = ChatEngine(agent=MockAgent("Simple text"))
        result = engine.invoke("Hello")

        components = result["messages"][1]["updateComponents"]["components"]
        root_ids = [c["id"] for c in components if c["id"] == "root"]
        self.assertEqual(len(root_ids), 1, "Must have exactly one root component")

    def test_invoke_updates_session(self):
        engine = ChatEngine(agent=MockAgent("Reply"))
        engine.invoke({"content": "User message"})

        session = engine.session
        self.assertEqual(len(session), 2)  # user + assistant
        self.assertEqual(session.messages[0].role, MessageRole.USER)
        self.assertEqual(session.messages[0].content, "User message")
        self.assertEqual(session.messages[1].role, MessageRole.ASSISTANT)

    def test_invoke_preserves_session_across_turns(self):
        engine = ChatEngine(agent=MockAgent("Reply"))
        engine.invoke({"content": "First"})
        engine.invoke({"content": "Second"})

        self.assertEqual(len(engine.session), 4)  # 2 user + 2 assistant

    def test_invoke_with_metadata(self):
        engine = ChatEngine(agent=MockAgent("Reply"))
        result = engine.invoke("Hello")

        metadata = result["metadata"]
        self.assertEqual(metadata.get("model"), "mock-model")
        self.assertEqual(metadata.get("tokens_used"), 42)

    def test_invoke_with_framework_adapter(self):
        adapter = MockFrameworkAdapter("Adapter reply")
        engine = ChatEngine(agent=adapter)
        result = engine.invoke("Hello")

        self.assertIn("messages", result)
        messages = result["messages"]
        self.assertTrue(len(messages) >= 2)

    def test_invoke_chart_content(self):
        """Agent returning chart data should produce ObChart component."""
        chart_data = {"type": "bar", "data": [{"name": "Q1", "value": 100}]}
        agent = MockAgent()
        agent.execute = lambda ctx: ExecutionResult(
            output=chart_data, status="success", metadata={},
        )
        engine = ChatEngine(agent=agent)
        result = engine.invoke("Show chart")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("ObChart", component_types)

    def test_invoke_file_content(self):
        """Agent returning file data should produce ObFileCard component."""
        file_data = {"name": "report.pdf", "url": "https://example.com/report.pdf"}
        agent = MockAgent()
        agent.execute = lambda ctx: ExecutionResult(
            output=file_data, status="success", metadata={},
        )
        engine = ChatEngine(agent=agent)
        result = engine.invoke("Show file")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("ObFileCard", component_types)

    def test_invoke_form_content(self):
        """Agent returning form data should produce input components."""
        form_data = {"fields": [{"name": "email", "type": "email", "label": "Email"}]}
        agent = MockAgent()
        agent.execute = lambda ctx: ExecutionResult(
            output=form_data, status="success", metadata={},
        )
        engine = ChatEngine(agent=agent)
        result = engine.invoke("Show form")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("TextField", component_types)
        self.assertIn("Button", component_types)

    def test_invoke_fallback_to_text(self):
        """Unknown content types should fall back to Text."""
        agent = MockAgent()
        agent.execute = lambda ctx: ExecutionResult(
            output=12345, status="success", metadata={},
        )
        engine = ChatEngine(agent=agent)
        result = engine.invoke("Show number")

        components = result["messages"][1]["updateComponents"]["components"]
        root = next(c for c in components if c["id"] == "root")
        self.assertEqual(root["component"], "Text")


class TestChatEngineStream(unittest.TestCase):
    """Tests for ChatEngine.stream()."""

    def test_stream_produces_jsonl(self):
        engine = ChatEngine(agent=MockAgent("Streamed reply"))
        lines = list(engine.stream("Hello"))

        # Should have: stream_start + 3 step_start/complete pairs + A2UI messages + stream_end
        self.assertTrue(len(lines) >= 10)

        # All lines should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            self.assertIsInstance(parsed, dict)

    def test_stream_envelope(self):
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = list(engine.stream("Hello"))

        # First: stream_start
        first = json.loads(lines[0])
        self.assertEqual(first["type"], "stream_start")
        self.assertIn("messageId", first)

        # Last: stream_end
        last = json.loads(lines[-1])
        self.assertEqual(last["type"], "stream_end")

    def test_stream_error_handling(self):
        """Stream should yield error message if engine fails."""
        agent = MockAgent()
        agent.execute = MagicMock(side_effect=RuntimeError("Agent error"))
        engine = ChatEngine(agent=agent)

        lines = list(engine.stream("Hello"))
        # Should have stream_start + step_start("Processing input") + error
        self.assertTrue(len(lines) >= 2)

        last = json.loads(lines[-1])
        self.assertEqual(last["type"], "error")
        self.assertIn("error", last.get("metadata", {}))

    def test_stream_has_three_steps(self):
        """Stream should emit exactly 3 step_start/step_complete pairs."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = list(engine.stream("Hello"))
        parsed = [json.loads(line) for line in lines]

        step_starts = [m for m in parsed if m.get("type") == "step_start"]
        step_completes = [m for m in parsed if m.get("type") == "step_complete"]

        self.assertEqual(len(step_starts), 3)
        self.assertEqual(len(step_completes), 3)

    def test_stream_step_names(self):
        """Steps should have correct names in order."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = list(engine.stream("Hello"))
        parsed = [json.loads(line) for line in lines]

        step_starts = [m for m in parsed if m.get("type") == "step_start"]
        names = [s["stepName"] for s in step_starts]

        self.assertEqual(names, ["Processing input", "Thinking", "Rendering response"])

    def test_stream_step_ids_are_unique(self):
        """Each step should have a unique stepId."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = list(engine.stream("Hello"))
        parsed = [json.loads(line) for line in lines]

        step_starts = [m for m in parsed if m.get("type") == "step_start"]
        step_ids = [s["stepId"] for s in step_starts]

        self.assertEqual(len(step_ids), len(set(step_ids)))

    def test_stream_step_message_id_matches_envelope(self):
        """step_start/step_complete messages should carry the stream messageId."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = list(engine.stream("Hello"))
        parsed = [json.loads(line) for line in lines]

        stream_start = parsed[0]
        message_id = stream_start["messageId"]

        steps = [m for m in parsed if m.get("type") in ("step_start", "step_complete")]
        for step in steps:
            self.assertEqual(step.get("messageId"), message_id)

    def test_stream_a2ui_messages_inside_rendering_step(self):
        """A2UI messages should appear between rendering step_start and step_complete."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = list(engine.stream("Hello"))
        parsed = [json.loads(line) for line in lines]

        # Find indices
        types = [m.get("type", "a2ui") if "version" not in m else "a2ui" for m in parsed]

        rendering_start_idx = None
        rendering_complete_idx = None
        for i, m in enumerate(parsed):
            if m.get("type") == "step_start" and m.get("stepName") == "Rendering response":
                rendering_start_idx = i
            if rendering_start_idx is not None and m.get("type") == "step_complete":
                if rendering_complete_idx is None and i > rendering_start_idx:
                    rendering_complete_idx = i

        self.assertIsNotNone(rendering_start_idx)
        self.assertIsNotNone(rendering_complete_idx)

        # A2UI messages should be between rendering_start and rendering_complete
        a2ui_indices = [i for i, m in enumerate(parsed) if "version" in m]
        for idx in a2ui_indices:
            self.assertGreater(idx, rendering_start_idx)
            self.assertLess(idx, rendering_complete_idx)


class TestChatEngineAsyncStream(unittest.TestCase):
    """Tests for ChatEngine.async_stream()."""

    def _run_async(self, coro):
        """Helper to run async code in tests."""
        return asyncio.get_event_loop().run_until_complete(coro)

    async def _collect_async_stream(self, engine, input_data):
        """Collect all lines from async_stream."""
        lines = []
        async for line in engine.async_stream(input_data):
            lines.append(line)
        return lines

    def test_async_stream_produces_same_output_as_sync(self):
        """async_stream should produce identical messages to sync stream."""
        engine_sync = ChatEngine(agent=MockAgent("Reply"))
        engine_async = ChatEngine(agent=MockAgent("Reply"))

        sync_lines = list(engine_sync.stream("Hello"))
        async_lines = self._run_async(self._collect_async_stream(engine_async, "Hello"))

        # Same number of messages
        self.assertEqual(len(sync_lines), len(async_lines))

        # Same message types in same order
        sync_types = [json.loads(l).get("type", "a2ui") for l in sync_lines]
        async_types = [json.loads(l).get("type", "a2ui") for l in async_lines]
        self.assertEqual(sync_types, async_types)

    def test_async_stream_has_three_steps(self):
        """async_stream should emit 3 step pairs."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = self._run_async(self._collect_async_stream(engine, "Hello"))
        parsed = [json.loads(line) for line in lines]

        step_starts = [m for m in parsed if m.get("type") == "step_start"]
        self.assertEqual(len(step_starts), 3)


class TestChatEngineComposition(unittest.TestCase):
    """Tests for ChatEngine composability with other Chainable components."""

    def test_pipe_operator(self):
        """ChatEngine should support | operator."""
        engine = ChatEngine(agent=MockAgent("Reply"))

        # Mock downstream component
        downstream = MagicMock()
        downstream.invoke = MagicMock(return_value={"result": "processed"})

        chain = engine | downstream
        self.assertIsNotNone(chain)

    def test_invoke_from_intelligence_layer_output(self):
        """ChatEngine should handle IntelligenceLayer output format."""
        engine = ChatEngine(agent=MockAgent())
        result = engine.invoke({
            "intelligence_output": "Processed data from agent",
            "metadata": {"layer": "intelligence"},
        })
        self.assertIn("messages", result)

    def test_invoke_from_data_layer_output(self):
        """ChatEngine should handle DataLayer output format."""
        engine = ChatEngine(agent=MockAgent())
        result = engine.invoke({
            "raw_data": ["Document 1 content", "Document 2 content"],
            "metadata": {"layer": "data"},
        })
        self.assertIn("messages", result)


if __name__ == "__main__":
    unittest.main()
