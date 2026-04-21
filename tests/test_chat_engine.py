"""Tests for ChatEngine."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import MagicMock

from openbench.chat.a2ui.schema import A2UI_VERSION
from openbench.chat.engine import ChatEngine
from openbench.chat.session import Attachment, ChatSession, MessageRole
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
            output=chart_data,
            status="success",
            metadata={},
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
            output=file_data,
            status="success",
            metadata={},
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
            output=form_data,
            status="success",
            metadata={},
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
            output=12345,
            status="success",
            metadata={},
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

        rendering_start_idx = None
        rendering_complete_idx = None
        for i, m in enumerate(parsed):
            if m.get("type") == "step_start" and m.get("stepName") == "Rendering response":
                rendering_start_idx = i
            if (
                rendering_start_idx is not None
                and m.get("type") == "step_complete"
                and rendering_complete_idx is None
                and i > rendering_start_idx
            ):
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
        return [line async for line in engine.async_stream(input_data)]

    def test_async_stream_produces_same_output_as_sync(self):
        """async_stream should produce identical messages to sync stream."""
        engine_sync = ChatEngine(agent=MockAgent("Reply"))
        engine_async = ChatEngine(agent=MockAgent("Reply"))

        sync_lines = list(engine_sync.stream("Hello"))
        async_lines = self._run_async(self._collect_async_stream(engine_async, "Hello"))

        # Same number of messages
        self.assertEqual(len(sync_lines), len(async_lines))

        # Same message types in same order
        sync_types = [json.loads(line).get("type", "a2ui") for line in sync_lines]
        async_types = [json.loads(line).get("type", "a2ui") for line in async_lines]
        self.assertEqual(sync_types, async_types)

    def test_async_stream_has_three_steps(self):
        """async_stream should emit 3 step pairs."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = self._run_async(self._collect_async_stream(engine, "Hello"))
        parsed = [json.loads(line) for line in lines]

        step_starts = [m for m in parsed if m.get("type") == "step_start"]
        self.assertEqual(len(step_starts), 3)

    def test_async_stream_error_handling(self):
        """async_stream should yield error message if agent fails."""
        agent = MockAgent()
        agent.execute = MagicMock(side_effect=RuntimeError("Agent error"))
        engine = ChatEngine(agent=agent)

        lines = self._run_async(self._collect_async_stream(engine, "Hello"))
        self.assertTrue(len(lines) >= 2)

        last = json.loads(lines[-1])
        self.assertEqual(last["type"], "error")
        self.assertIn("error", last.get("metadata", {}))

    def _collect_components(self, messages):
        """Pull components out of updateComponents messages.

        A2UI v0.10 flattens property keys onto the component object, so
        variant/title/message appear as direct keys, not nested in a
        'properties' dict.
        """
        components = []
        for msg in messages:
            update = msg.get("updateComponents")
            if not update:
                continue
            components.extend(update.get("components", []))
        return components

    def test_invoke_failed_result_renders_error_callout(self):
        """ExecutionResult(status='failed') should render as ObCallout in invoke()."""
        agent = MockAgent()
        agent.execute = MagicMock(
            return_value=ExecutionResult(
                output=None,
                status="failed",
                metadata={"error": "400 INVALID_ARGUMENT: schema is broken"},
            )
        )
        engine = ChatEngine(agent=agent)
        result = engine.invoke("Hello")

        components = self._collect_components(result["messages"])
        error_callouts = [
            c
            for c in components
            if c.get("component") == "ObCallout" and c.get("variant") == "error"
        ]
        self.assertEqual(len(error_callouts), 1)
        self.assertIn("400 INVALID_ARGUMENT", error_callouts[0]["message"])
        self.assertEqual(error_callouts[0]["title"], "Agent execution failed")

    def test_stream_failed_result_renders_error_callout(self):
        """ExecutionResult(status='failed') should render as ObCallout in stream()."""
        agent = MockAgent()
        agent.execute = MagicMock(
            return_value=ExecutionResult(
                output=None,
                status="failed",
                metadata={"error": "some tool rejected"},
            )
        )
        engine = ChatEngine(agent=agent)

        lines = list(engine.stream("Hello"))
        parsed = [json.loads(ln) for ln in lines]
        components = self._collect_components(parsed)

        error_callouts = [
            c
            for c in components
            if c.get("component") == "ObCallout" and c.get("variant") == "error"
        ]
        self.assertEqual(len(error_callouts), 1)
        self.assertIn("some tool rejected", error_callouts[0]["message"])

        # Stream should still complete cleanly
        last = parsed[-1]
        self.assertEqual(last["type"], "stream_end")

    def test_async_stream_step_names(self):
        """async_stream steps should have correct names."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        lines = self._run_async(self._collect_async_stream(engine, "Hello"))
        parsed = [json.loads(line) for line in lines]

        step_starts = [m for m in parsed if m.get("type") == "step_start"]
        names = [s["stepName"] for s in step_starts]

        self.assertEqual(names, ["Processing input", "Thinking", "Rendering response"])


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
        result = engine.invoke(
            {
                "intelligence_output": "Processed data from agent",
                "metadata": {"layer": "intelligence"},
            }
        )
        self.assertIn("messages", result)

    def test_invoke_from_data_layer_output(self):
        """ChatEngine should handle DataLayer output format."""
        engine = ChatEngine(agent=MockAgent())
        result = engine.invoke(
            {
                "raw_data": ["Document 1 content", "Document 2 content"],
                "metadata": {"layer": "data"},
            }
        )
        self.assertIn("messages", result)


class TestChatEngineAttachments(unittest.TestCase):
    """Tests for ChatEngine attachment threading to agent."""

    def test_invoke_with_attachments_passes_context(self):
        """Attachments with extracted_text are threaded to agent via ExecutionContext."""
        agent = MockAgent("Got it!")
        captured_contexts: list[ExecutionContext] = []
        original_execute = agent.execute

        def capturing_execute(ctx):
            captured_contexts.append(ctx)
            return original_execute(ctx)

        agent.execute = capturing_execute
        engine = ChatEngine(agent=agent)

        attachments = [
            Attachment(
                id="att-1",
                type="file",
                name="doc.pdf",
                url="/uploads/doc.pdf",
                mime_type="application/pdf",
                extracted_text="This is the PDF content.",
            )
        ]
        engine.invoke(
            {
                "content": "Summarize this",
                "attachments": [a.to_dict() for a in attachments],
            }
        )

        self.assertEqual(len(captured_contexts), 1)
        ctx = captured_contexts[0]
        self.assertIn("attachments", ctx.data)
        self.assertEqual(len(ctx.data["attachments"]), 1)
        self.assertEqual(ctx.data["attachments"][0]["name"], "doc.pdf")
        self.assertEqual(ctx.data["attachments"][0]["content"], "This is the PDF content.")

    def test_invoke_without_attachments_unchanged(self):
        """Invoke without attachments should not include attachments key in data."""
        agent = MockAgent("Reply")
        captured_contexts: list[ExecutionContext] = []
        original_execute = agent.execute

        def capturing_execute(ctx):
            captured_contexts.append(ctx)
            return original_execute(ctx)

        agent.execute = capturing_execute
        engine = ChatEngine(agent=agent)
        engine.invoke({"content": "Hello"})

        self.assertEqual(len(captured_contexts), 1)
        self.assertNotIn("attachments", captured_contexts[0].data)

    def test_invoke_skips_attachments_without_extracted_text(self):
        """Attachments without extracted_text are filtered out."""
        agent = MockAgent("Reply")
        captured_contexts: list[ExecutionContext] = []
        original_execute = agent.execute

        def capturing_execute(ctx):
            captured_contexts.append(ctx)
            return original_execute(ctx)

        agent.execute = capturing_execute
        engine = ChatEngine(agent=agent)

        attachments = [
            Attachment(
                id="att-1",
                type="image",
                name="photo.png",
                url="/uploads/photo.png",
                mime_type="image/png",
            )
        ]
        engine.invoke(
            {
                "content": "What's this?",
                "attachments": [a.to_dict() for a in attachments],
            }
        )

        self.assertEqual(len(captured_contexts), 1)
        # No attachments key since none had extracted_text
        self.assertNotIn("attachments", captured_contexts[0].data)


class TestChatEngineRenderItems(unittest.TestCase):
    """Tests for ChatEngine render_items_fn (visualization tools side-channel)."""

    def test_invoke_with_chart_render_item(self):
        """render_items_fn returning chart dict should produce ObChart component."""
        chart_item = {
            "type": "bar",
            "title": "Sales",
            "data": [{"name": "Q1", "value": 100}],
        }
        engine = ChatEngine(
            agent=MockAgent("Here's the chart:"),
            render_items_fn=lambda: [chart_item],
        )
        result = engine.invoke("Show sales chart")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("ObChart", component_types)
        # Text content should also be present (ObMarkdown or Text)
        has_text = any(c["component"] in ("ObMarkdown", "Text") for c in components)
        self.assertTrue(has_text, "Should have text alongside chart")

    def test_invoke_with_form_render_item(self):
        """render_items_fn returning form dict should produce form components."""
        form_item = {
            "fields": [
                {"name": "email", "type": "email", "label": "Email", "required": True},
                {"name": "name", "type": "text", "label": "Name"},
            ],
            "submitLabel": "Send",
        }
        engine = ChatEngine(
            agent=MockAgent("Please fill out this form:"),
            render_items_fn=lambda: [form_item],
        )
        result = engine.invoke("Create feedback form")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("TextField", component_types)
        self.assertIn("Button", component_types)

    def test_invoke_with_file_render_item(self):
        """render_items_fn returning file dict should produce ObFileCard component."""
        file_item = {"name": "report.pdf", "url": "https://example.com/report.pdf"}
        engine = ChatEngine(
            agent=MockAgent("Here's your file:"),
            render_items_fn=lambda: [file_item],
        )
        result = engine.invoke("Show report")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("ObFileCard", component_types)

    def test_invoke_no_render_items_regression(self):
        """Engine with render_items_fn returning empty list should render normally."""
        engine = ChatEngine(
            agent=MockAgent("Just text"),
            render_items_fn=list,
        )
        result = engine.invoke("Hello")

        components = result["messages"][1]["updateComponents"]["components"]
        # Should only have text components, no chart/form/file
        component_types = [c["component"] for c in components]
        self.assertNotIn("ObChart", component_types)
        self.assertNotIn("ObFileCard", component_types)

    def test_invoke_without_render_items_fn(self):
        """Engine without render_items_fn should work normally (backward compat)."""
        engine = ChatEngine(agent=MockAgent("Normal reply"))
        result = engine.invoke("Hello")

        self.assertIn("messages", result)
        components = result["messages"][1]["updateComponents"]["components"]
        self.assertTrue(len(components) > 0)

    def test_invoke_mixed_text_and_chart(self):
        """Text agent output + chart render item should produce both components."""
        chart_item = {
            "type": "pie",
            "title": "Funding",
            "data": [{"name": "AI", "value": 40}, {"name": "Bio", "value": 30}],
        }
        engine = ChatEngine(
            agent=MockAgent("AI leads in funding allocation:"),
            render_items_fn=lambda: [chart_item],
        )
        result = engine.invoke("Show funding breakdown")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]

        # Should have both text and chart
        has_text = any(t in ("ObMarkdown", "Text") for t in component_types)
        has_chart = "ObChart" in component_types
        self.assertTrue(has_text, "Should have text component")
        self.assertTrue(has_chart, "Should have ObChart component")

    def test_invoke_multiple_render_items(self):
        """Multiple render items should all be rendered."""
        items = [
            {"type": "bar", "data": [{"x": 1, "y": 2}]},
            {"name": "data.csv", "url": "/files/data.csv"},
        ]
        engine = ChatEngine(
            agent=MockAgent("Analysis complete:"),
            render_items_fn=lambda: items,
        )
        result = engine.invoke("Analyze data")

        components = result["messages"][1]["updateComponents"]["components"]
        component_types = [c["component"] for c in components]
        self.assertIn("ObChart", component_types)
        self.assertIn("ObFileCard", component_types)

    def test_stream_with_render_items(self):
        """stream() should include render items in output."""
        chart_item = {"type": "line", "data": [{"x": 1, "y": 10}]}
        engine = ChatEngine(
            agent=MockAgent("Trend data:"),
            render_items_fn=lambda: [chart_item],
        )
        lines = list(engine.stream("Show trend"))

        # Find the updateComponents message
        all_components = []
        for line in lines:
            parsed = json.loads(line)
            if "updateComponents" in parsed:
                all_components.extend(parsed["updateComponents"]["components"])

        component_types = [c["component"] for c in all_components]
        self.assertIn("ObChart", component_types)

    # -- Deduplication tests --

    def test_duplicate_forms_deduped_to_last(self):
        """If render_items_fn returns duplicate forms, only the last one is rendered."""
        forms = [
            {
                "fields": [{"name": "a", "type": "text", "label": "A"}],
                "title": "Form v1",
            },
            {
                "fields": [{"name": "b", "type": "text", "label": "B"}],
                "title": "Form v2",
            },
        ]
        engine = ChatEngine(
            agent=MockAgent("Here's the form:"),
            render_items_fn=lambda: forms,
        )
        result = engine.invoke("Create form")

        components = result["messages"][1]["updateComponents"]["components"]
        # Should only have one Card (from last form), not two
        cards = [c for c in components if c["component"] == "Card"]
        self.assertEqual(len(cards), 1, "Duplicate forms should be deduped to one")

        # The surviving form should be "Form v2" (the last one)
        text_components = [c for c in components if c["component"] == "Text"]
        titles = [c for c in text_components if c.get("variant") == "h4"]
        self.assertTrue(
            any(t["text"] == "Form v2" for t in titles),
            "Last form ('Form v2') should survive deduplication",
        )

    def test_duplicate_charts_same_title_deduped(self):
        """Charts with the same title should be deduped (last wins)."""
        charts = [
            {"type": "bar", "title": "Sales", "data": [{"x": "Q1", "y": 100}]},
            {"type": "line", "title": "Sales", "data": [{"x": "Q1", "y": 200}]},
        ]
        engine = ChatEngine(
            agent=MockAgent("Updated chart:"),
            render_items_fn=lambda: charts,
        )
        result = engine.invoke("Show sales")

        components = result["messages"][1]["updateComponents"]["components"]
        ob_charts = [c for c in components if c["component"] == "ObChart"]
        self.assertEqual(len(ob_charts), 1, "Same-title charts should be deduped")

    def test_different_chart_titles_kept(self):
        """Charts with different titles should all be kept."""
        charts = [
            {"type": "bar", "title": "Sales", "data": [{"x": "Q1", "y": 100}]},
            {"type": "pie", "title": "Revenue", "data": [{"x": "AI", "y": 40}]},
        ]
        engine = ChatEngine(
            agent=MockAgent("Two charts:"),
            render_items_fn=lambda: charts,
        )
        result = engine.invoke("Compare")

        components = result["messages"][1]["updateComponents"]["components"]
        ob_charts = [c for c in components if c["component"] == "ObChart"]
        self.assertEqual(len(ob_charts), 2, "Different-title charts should both render")

    def test_duplicate_file_cards_deduped(self):
        """File cards with the same name should be deduped (last wins)."""
        files = [
            {"name": "report.pdf", "url": "/old/report.pdf"},
            {"name": "report.pdf", "url": "/new/report.pdf"},
        ]
        engine = ChatEngine(
            agent=MockAgent("Updated file:"),
            render_items_fn=lambda: files,
        )
        result = engine.invoke("Show file")

        components = result["messages"][1]["updateComponents"]["components"]
        file_cards = [c for c in components if c["component"] == "ObFileCard"]
        self.assertEqual(len(file_cards), 1, "Same-name file cards should be deduped")


class TestChatEngineClearRenderItems(unittest.TestCase):
    """Regression tests for clear_render_items_fn wiring (Issue 2).

    The docstring on ``ChatEngine.__init__`` promises that
    ``clear_render_items_fn`` is "Called before each agent execution for
    per-request isolation." Before the fix, the callback was stored but
    never invoked — so stale render items bled across turns.
    """

    def test_invoke_calls_clear_before_execution(self):
        clear_calls: list[int] = []
        engine = ChatEngine(
            agent=MockAgent("Reply"),
            clear_render_items_fn=lambda: clear_calls.append(1),
        )
        engine.invoke("Hello")
        self.assertEqual(len(clear_calls), 1)

    def test_invoke_calls_clear_on_every_turn(self):
        clear_calls: list[int] = []
        engine = ChatEngine(
            agent=MockAgent("Reply"),
            clear_render_items_fn=lambda: clear_calls.append(1),
        )
        engine.invoke("Turn 1")
        engine.invoke("Turn 2")
        engine.invoke("Turn 3")
        self.assertEqual(len(clear_calls), 3)

    def test_stream_calls_clear_before_execution(self):
        clear_calls: list[int] = []
        engine = ChatEngine(
            agent=MockAgent("Reply"),
            clear_render_items_fn=lambda: clear_calls.append(1),
        )
        list(engine.stream("Hello"))
        self.assertEqual(len(clear_calls), 1)

    def test_async_stream_calls_clear_before_execution(self):
        clear_calls: list[int] = []
        engine = ChatEngine(
            agent=MockAgent("Reply"),
            clear_render_items_fn=lambda: clear_calls.append(1),
        )

        async def collect():
            async for _ in engine.async_stream("Hello"):
                pass

        asyncio.run(collect())
        self.assertEqual(len(clear_calls), 1)

    def test_clear_called_before_render_items_fn(self):
        """clear_render_items_fn must fire BEFORE the agent runs, so that
        stale items from a previous turn do not leak into render_items_fn.
        """
        call_order: list[str] = []

        # Simulate a process-global queue.
        queue: list[dict] = [{"type": "bar", "title": "Stale chart", "data": []}]

        def clear():
            call_order.append("clear")
            queue.clear()

        def render_items():
            call_order.append("render_items")
            return list(queue)

        engine = ChatEngine(
            agent=MockAgent("Reply"),
            clear_render_items_fn=clear,
            render_items_fn=render_items,
        )
        result = engine.invoke("Hello")

        # clear must happen before render_items is collected
        self.assertEqual(call_order[0], "clear")
        self.assertIn("render_items", call_order)
        self.assertLess(call_order.index("clear"), call_order.index("render_items"))

        # The stale chart must NOT appear in the output
        components = result["messages"][1]["updateComponents"]["components"]
        ob_charts = [c for c in components if c["component"] == "ObChart"]
        self.assertEqual(
            len(ob_charts),
            0,
            "Stale chart from previous turn should have been cleared before execution",
        )

    def test_no_clear_fn_is_safe(self):
        """When clear_render_items_fn is None, invoke() must still work."""
        engine = ChatEngine(agent=MockAgent("Reply"))
        result = engine.invoke("Hello")
        self.assertIn("messages", result)

    def test_clear_fn_exception_does_not_break_invoke(self):
        """If clear_render_items_fn raises, the turn must still complete."""

        def bad_clear():
            raise RuntimeError("boom")

        engine = ChatEngine(
            agent=MockAgent("Reply"),
            clear_render_items_fn=bad_clear,
        )
        # Should not propagate the RuntimeError
        result = engine.invoke("Hello")
        self.assertIn("messages", result)


class TestChatEngineSessionStore(unittest.TestCase):
    """ChatEngine persists the session after each turn when a store is set."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from openbench.chat.stores.sqlite import SQLiteSessionStore

        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteSessionStore(str(Path(self._tmpdir.name) / "sessions.db"))

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_invoke_persists_session(self):
        engine = ChatEngine(agent=MockAgent("Reply"), session_store=self.store)
        engine.invoke("Hi")
        reloaded = self.store.load(engine.session.session_id)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        # Two messages: user + assistant
        self.assertEqual(len(reloaded.messages), 2)
        self.assertEqual(reloaded.messages[0].role, MessageRole.USER)
        self.assertEqual(reloaded.messages[1].role, MessageRole.ASSISTANT)

    def test_invoke_persists_twice_per_turn(self):
        """Session saved after user message AND after assistant message."""

        class CountingStore:
            def __init__(self, inner):
                self.inner = inner
                self.saves = 0

            def save(self, session):
                self.saves += 1
                self.inner.save(session)

            def load(self, session_id):
                return self.inner.load(session_id)

            def list(self, limit=50, offset=0):
                return self.inner.list(limit=limit, offset=offset)

            def delete(self, session_id):
                self.inner.delete(session_id)

        counter = CountingStore(self.store)
        engine = ChatEngine(agent=MockAgent("Reply"), session_store=counter)
        engine.invoke("Hi")
        # One save after user message, one after assistant
        self.assertEqual(counter.saves, 2)

    def test_stream_persists_session(self):
        engine = ChatEngine(agent=MockAgent("Reply"), session_store=self.store)
        for _ in engine.stream("Streaming hi"):
            pass
        reloaded = self.store.load(engine.session.session_id)
        assert reloaded is not None
        self.assertEqual(len(reloaded.messages), 2)

    def test_store_failure_does_not_break_turn(self):
        """A transient store exception must not sink the live turn."""

        class BrokenStore:
            def save(self, session):
                raise RuntimeError("disk full")

            def load(self, session_id):
                return None

            def list(self, limit=50, offset=0):
                return []

            def delete(self, session_id):
                pass

        engine = ChatEngine(agent=MockAgent("Reply"), session_store=BrokenStore())
        result = engine.invoke("Hi")
        self.assertIn("messages", result)
        # In-memory session still intact
        self.assertEqual(len(engine.session.messages), 2)

    def test_no_store_means_no_persist(self):
        engine = ChatEngine(agent=MockAgent("Reply"), session_store=None)
        engine.invoke("Hi")
        self.assertIsNone(self.store.load(engine.session.session_id))


class _RaisingAgent(Agent):
    """Agent that always raises to simulate a mid-turn crash."""

    def __init__(self, exc: BaseException):
        self._exc = exc

    @property
    def agent_type(self) -> str:
        return "raising"

    def execute(self, context):
        raise self._exc

    def estimate_cost(self, context):
        return 0.0


class TestChatEngineAbortPlaceholder(unittest.TestCase):
    """Layer 2b — aborted-turn placeholder.

    When ``_execute_agent`` raises, ``invoke`` / ``stream`` /
    ``async_stream`` must leave the session ending on a placeholder
    assistant message (``metadata["aborted"] == True``) and propagate
    the exception (for invoke) or emit a stream ERROR (for stream).
    """

    def setUp(self):
        import tempfile
        from pathlib import Path

        from openbench.chat.stores.sqlite import SQLiteSessionStore

        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteSessionStore(str(Path(self._tmpdir.name) / "sessions.db"))

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_invoke_writes_placeholder_on_crash(self):
        engine = ChatEngine(
            agent=_RaisingAgent(RuntimeError("Gemini 500")),
            session_store=self.store,
        )
        with self.assertRaises(RuntimeError):
            engine.invoke("analyze this")

        # In-memory session ended on placeholder
        msgs = engine.session.messages
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, MessageRole.USER)
        self.assertEqual(msgs[0].content, "analyze this")
        self.assertEqual(msgs[1].role, MessageRole.ASSISTANT)
        self.assertIn("Turn interrupted", msgs[1].content)
        self.assertTrue(msgs[1].metadata.get("aborted"))
        self.assertIn("Gemini 500", msgs[1].metadata.get("error", ""))

        # Session saved to store with both messages
        reloaded = self.store.load(engine.session.session_id)
        assert reloaded is not None
        self.assertEqual(len(reloaded.messages), 2)
        self.assertTrue(reloaded.messages[1].metadata.get("aborted"))

    def test_stream_writes_placeholder_on_crash(self):
        engine = ChatEngine(
            agent=_RaisingAgent(RuntimeError("tool exploded")),
            session_store=self.store,
        )
        # Consume the stream so the except handler runs
        output = list(engine.stream("something"))
        # Last emitted stream message is an ERROR type
        last = json.loads(output[-1])
        self.assertEqual(last["type"], "error")

        # Placeholder persisted
        reloaded = self.store.load(engine.session.session_id)
        assert reloaded is not None
        self.assertEqual(len(reloaded.messages), 2)
        self.assertTrue(reloaded.messages[1].metadata.get("aborted"))
        self.assertIn("Turn interrupted", reloaded.messages[1].content)

    def test_async_stream_writes_placeholder_on_crash(self):
        engine = ChatEngine(
            agent=_RaisingAgent(RuntimeError("async boom")),
            session_store=self.store,
        )

        async def _collect():
            return [line async for line in engine.async_stream("hi")]

        loop = asyncio.new_event_loop()
        try:
            output = loop.run_until_complete(_collect())
        finally:
            loop.close()
        self.assertEqual(json.loads(output[-1])["type"], "error")

        reloaded = self.store.load(engine.session.session_id)
        assert reloaded is not None
        self.assertEqual(len(reloaded.messages), 2)
        self.assertTrue(reloaded.messages[1].metadata.get("aborted"))

    def test_placeholder_disabled_by_env(
        self,
    ):
        """With the env flag off, the session ends on the user message —
        matches pre-Layer-2b behaviour, useful as a rollback lever."""
        import os

        os.environ["OPENBENCH_PLACEHOLDER_ON_ABORT"] = "0"
        try:
            engine = ChatEngine(
                agent=_RaisingAgent(RuntimeError("x")),
                session_store=self.store,
            )
            with self.assertRaises(RuntimeError):
                engine.invoke("q")

            # No placeholder added
            self.assertEqual(len(engine.session.messages), 1)
            self.assertEqual(engine.session.messages[0].role, MessageRole.USER)

            # Store has only the user message (from the upfront save)
            reloaded = self.store.load(engine.session.session_id)
            assert reloaded is not None
            self.assertEqual(len(reloaded.messages), 1)
        finally:
            del os.environ["OPENBENCH_PLACEHOLDER_ON_ABORT"]

    def test_placeholder_store_failure_does_not_mask_original_exception(self):
        """If the placeholder save itself raises, the ORIGINAL exception
        from the agent must still propagate unchanged."""

        class BrokenStore:
            def save(self, session):
                raise OSError("disk full")

            def load(self, session_id):
                return None

            def list(self, limit=50, offset=0):
                return []

            def delete(self, session_id):
                pass

        engine = ChatEngine(
            agent=_RaisingAgent(RuntimeError("original")),
            session_store=BrokenStore(),
        )
        with self.assertRaises(RuntimeError) as cm:
            engine.invoke("hi")
        # The original exception propagates — not the disk-full OSError
        self.assertIn("original", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
