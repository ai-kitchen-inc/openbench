"""Tests for ChatLayer L2 orchestrator."""

import unittest

from openbench.chat.layer import ChatFactory, ChatLayer
from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
)
from openbench.core.layers import DataLayer


class MockAgent(Agent):
    """Mock agent for testing ChatLayer."""

    def __init__(self, response: str = "Layer reply"):
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


class TestChatLayer(unittest.TestCase):
    """Tests for ChatLayer."""

    def test_init(self):
        layer = ChatLayer(agent=MockAgent())
        self.assertIsNotNone(layer.engine)

    def test_invoke_direct(self):
        layer = ChatLayer(agent=MockAgent("Hello!"))
        result = layer.invoke({"content": "Hi"})

        self.assertIn("chat_output", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["layer"], "chat")

    def test_invoke_string_input(self):
        layer = ChatLayer(agent=MockAgent("Reply"))
        result = layer.invoke("Hello world")

        self.assertIn("chat_output", result)
        chat_output = result["chat_output"]
        self.assertIn("messages", chat_output)

    def test_invoke_preserves_keys(self):
        layer = ChatLayer(agent=MockAgent())
        result = layer.invoke(
            {
                "content": "Hello",
                "goal": "Test goal",
                "output_path": "/tmp/test",
                "title": "Test Title",
            }
        )

        self.assertEqual(result.get("goal"), "Test goal")
        self.assertEqual(result.get("output_path"), "/tmp/test")
        self.assertEqual(result.get("title"), "Test Title")

    def test_invoke_from_data_layer_output(self):
        """ChatLayer should handle DataLayer output format."""
        layer = ChatLayer(agent=MockAgent())
        data_output = {
            "raw_data": ["Document content here"],
            "indexed_ids": [],
            "metadata": {"layer": "data"},
        }
        result = layer.invoke(data_output)
        self.assertIn("chat_output", result)

    def test_invoke_from_intelligence_layer_output(self):
        """ChatLayer should handle IntelligenceLayer output format."""
        layer = ChatLayer(agent=MockAgent())
        intel_output = {
            "intelligence_output": "Analysis result",
            "metadata": {"layer": "intelligence"},
        }
        result = layer.invoke(intel_output)
        self.assertIn("chat_output", result)

    def test_metadata_num_messages(self):
        layer = ChatLayer(agent=MockAgent())
        result = layer.invoke({"content": "Hi"})
        self.assertIn("num_messages", result["metadata"])
        self.assertGreater(result["metadata"]["num_messages"], 0)

    def test_chat_output_has_a2ui_messages(self):
        layer = ChatLayer(agent=MockAgent("Test"))
        result = layer.invoke({"content": "Hello"})

        chat_output = result["chat_output"]
        messages = chat_output["messages"]
        self.assertTrue(len(messages) >= 2)

        # First: createSurface
        self.assertIn("createSurface", messages[0])
        # Second: updateComponents
        self.assertIn("updateComponents", messages[1])


class TestChatLayerComposition(unittest.TestCase):
    """Tests for ChatLayer composition with other L2 layers."""

    def test_pipe_operator(self):
        """ChatLayer should support | operator for L2 composition."""
        layer = ChatLayer(agent=MockAgent())
        # Just verify the pipe operator works (creates a Chain)
        from openbench.core.chainable import Chainable

        self.assertIsInstance(layer, Chainable)

    def test_compose_with_data_layer(self):
        """DataLayer | ChatLayer should work."""
        from openbench.core.abstractions import DataSource, RawData

        class MockSource(DataSource):
            @property
            def source_type(self) -> str:
                return "mock"

            @property
            def source_id(self) -> str:
                return "mock-1"

            def get_metadata(self):
                return {}

            def extract(self) -> RawData:
                return RawData(
                    content="PDF content here",
                    content_type="text",
                    metadata={},
                    source=self,
                )

            def validate(self):
                return True

        workflow = DataLayer(sources=MockSource()) | ChatLayer(agent=MockAgent())
        result = workflow.invoke({})

        # Should have chat_output from ChatLayer
        self.assertIn("chat_output", result)


class TestChatFactory(unittest.TestCase):
    """Tests for ChatFactory."""

    def test_create(self):
        layer = ChatFactory.create(agent=MockAgent())
        self.assertIsInstance(layer, ChatLayer)

    def test_create_with_catalog(self):
        layer = ChatFactory.create(agent=MockAgent(), catalog_id="custom:v1")
        self.assertEqual(layer.engine.builder.catalog_id, "custom:v1")


if __name__ == "__main__":
    unittest.main()
