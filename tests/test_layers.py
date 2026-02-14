"""Tests for L2 Layer classes."""

from __future__ import annotations

import unittest
from typing import Any

from openbench.core import (
    Agent,
    Chain,
    DataLayer,
    DataSource,
    DataStore,
    ExecutionContext,
    ExecutionResult,
    GeneratedOutput,
    IntelligenceLayer,
    OutputGenerator,
    OutputLayer,
    Parallel,
    Query,
    RawData,
    SearchResult,
    create_workflow,
)


# Test implementations
class MockSource(DataSource):
    def __init__(self, name: str):
        self.name = name

    @property
    def source_type(self) -> str:
        return "mock"

    @property
    def source_id(self) -> str:
        return f"mock:{self.name}"

    def get_metadata(self) -> dict[str, Any]:
        return {"name": self.name}

    def extract(self) -> RawData:
        return RawData(f"data from {self.name}", "text", {}, self)

    def validate(self) -> bool:
        return True


class MockStore(DataStore):
    def __init__(self):
        self._data = []

    @property
    def store_type(self) -> str:
        return "mock"

    def index(self, data: RawData, **options) -> str:
        item_id = f"item_{len(self._data)}"
        self._data.append({"id": item_id, "data": data})
        return item_id

    def search(self, query: Query) -> SearchResult:
        return SearchResult(items=self._data, total=len(self._data))

    def get(self, item_id: str) -> Any | None:
        return next((item for item in self._data if item["id"] == item_id), None)

    def delete(self, item_id: str) -> bool:
        return True

    def update(self, item_id: str, data: Any) -> bool:
        return True


class MockAgent(Agent):
    def __init__(self, name: str):
        self.name = name

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output={f"{self.name}_result": f"completed {self.name}"},
            status="completed",
            metadata={"agent": self.name},
            cost=0.0,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class MockGenerator(OutputGenerator):
    def __init__(self, format: str):
        self._format = format

    @property
    def output_format(self) -> str:
        return self._format

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        return GeneratedOutput(
            file_path=f"/tmp/test.{self._format}",
            format=self._format,
            size_bytes=100,
            metadata={},
        )

    def validate(self, content: Any) -> bool:
        return True


class TestDataLayer(unittest.TestCase):
    """Test DataLayer (L2)."""

    def test_data_layer_creation(self):
        """Test DataLayer creation."""
        source = MockSource("test")
        store = MockStore()

        layer = DataLayer(sources=source, stores=[store])

        self.assertIsNotNone(layer.sources)
        self.assertEqual(len(layer.stores), 1)

    def test_data_layer_invoke(self):
        """Test DataLayer invoke."""
        source = MockSource("test")
        store = MockStore()

        layer = DataLayer(sources=source, stores=[store])
        result = layer.invoke({})

        self.assertIn("raw_data", result)
        self.assertIn("indexed_ids", result)
        self.assertIn("metadata", result)

        # Check metadata
        self.assertEqual(result["metadata"]["layer"], "data")
        self.assertGreater(result["metadata"]["num_indexed"], 0)

    def test_data_layer_with_multiple_sources(self):
        """Test DataLayer with parallel sources."""
        source1 = MockSource("source1")
        source2 = MockSource("source2")
        source3 = MockSource("source3")

        # Parallel sources
        sources = Parallel([source1, source2, source3])
        store = MockStore()

        layer = DataLayer(sources=sources, stores=[store])
        result = layer.invoke({})

        # Should have indexed all sources
        self.assertEqual(len(result["indexed_ids"]), 3)

    def test_data_layer_with_sequential_sources(self):
        """Test DataLayer with sequential sources."""
        source1 = MockSource("source1")
        source2 = MockSource("source2")

        # Sequential sources
        sources = Chain([source1, source2])
        store = MockStore()

        layer = DataLayer(sources=sources, stores=[store])
        result = layer.invoke({})

        self.assertIn("raw_data", result)

    def test_data_layer_chainable(self):
        """Test DataLayer is Chainable."""
        source = MockSource("test")
        layer = DataLayer(sources=source)

        # Should be chainable with other layers
        from openbench.core import Chainable

        self.assertIsInstance(layer, Chainable)


class TestIntelligenceLayer(unittest.TestCase):
    """Test IntelligenceLayer (L2)."""

    def test_intelligence_layer_creation(self):
        """Test IntelligenceLayer creation."""
        agent = MockAgent("test")

        layer = IntelligenceLayer(agents=agent)

        self.assertIsNotNone(layer.agents)

    def test_intelligence_layer_invoke(self):
        """Test IntelligenceLayer invoke."""
        agent = MockAgent("test")

        layer = IntelligenceLayer(agents=agent)
        result = layer.invoke({})

        self.assertIn("intelligence_output", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["layer"], "intelligence")

    def test_intelligence_layer_with_multiple_agents(self):
        """Test IntelligenceLayer with sequential agents."""
        agent1 = MockAgent("agent1")
        agent2 = MockAgent("agent2")
        agent3 = MockAgent("agent3")

        # Sequential agents
        agents = Chain([agent1, agent2, agent3])

        layer = IntelligenceLayer(agents=agents)
        result = layer.invoke({})

        self.assertIn("intelligence_output", result)

    def test_intelligence_layer_with_parallel_agents(self):
        """Test IntelligenceLayer with parallel agents."""
        agent1 = MockAgent("agent1")
        agent2 = MockAgent("agent2")

        # Parallel agents
        agents = Parallel([agent1, agent2])

        layer = IntelligenceLayer(agents=agents)
        result = layer.invoke({})

        # Output should contain results from both agents
        self.assertIn("intelligence_output", result)

    def test_intelligence_layer_chainable(self):
        """Test IntelligenceLayer is Chainable."""
        agent = MockAgent("test")
        layer = IntelligenceLayer(agents=agent)

        from openbench.core import Chainable

        self.assertIsInstance(layer, Chainable)


class TestOutputLayer(unittest.TestCase):
    """Test OutputLayer (L2)."""

    def test_output_layer_creation(self):
        """Test OutputLayer creation."""
        generator = MockGenerator("pdf")

        layer = OutputLayer(generators=generator)

        self.assertIsNotNone(layer.generators)

    def test_output_layer_invoke(self):
        """Test OutputLayer invoke."""
        generator = MockGenerator("pdf")

        layer = OutputLayer(generators=generator)
        result = layer.invoke({})

        self.assertIn("generated_outputs", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["layer"], "output")
        self.assertGreater(result["metadata"]["num_outputs"], 0)

    def test_output_layer_with_multiple_generators(self):
        """Test OutputLayer with parallel generators."""
        pdf_gen = MockGenerator("pdf")
        pptx_gen = MockGenerator("pptx")

        # Parallel generators
        generators = Parallel([pdf_gen, pptx_gen])

        layer = OutputLayer(generators=generators)
        result = layer.invoke({})

        # Should have generated both outputs
        self.assertEqual(len(result["generated_outputs"]), 2)

    def test_output_layer_chainable(self):
        """Test OutputLayer is Chainable."""
        generator = MockGenerator("pdf")
        layer = OutputLayer(generators=generator)

        from openbench.core import Chainable

        self.assertIsInstance(layer, Chainable)


class TestLayerComposition(unittest.TestCase):
    """Test L2 layer composition."""

    def test_layer_composition(self):
        """Test composing DataLayer | IntelligenceLayer | OutputLayer."""
        # Create layers
        source = MockSource("test")
        store = MockStore()
        agent = MockAgent("test")
        generator = MockGenerator("pdf")

        data_layer = DataLayer(sources=source, stores=[store])
        intelligence_layer = IntelligenceLayer(agents=agent)
        output_layer = OutputLayer(generators=generator)

        # Compose layers
        pipeline = data_layer | intelligence_layer | output_layer

        # Execute
        result = pipeline.invoke({})

        # Final result should be from output layer
        self.assertIn("generated_outputs", result)

    def test_complex_layer_composition(self):
        """Test complex L1 + L2 composition."""
        # L1: Parallel sources
        source1 = MockSource("source1")
        source2 = MockSource("source2")
        sources = Parallel([source1, source2])

        # L1: Sequential agents
        agent1 = MockAgent("agent1")
        agent2 = MockAgent("agent2")
        agents = Chain([agent1, agent2])

        # L1: Parallel outputs
        pdf = MockGenerator("pdf")
        pptx = MockGenerator("pptx")
        outputs = Parallel([pdf, pptx])

        # L2: Compose layers
        data_layer = DataLayer(sources=sources, stores=[MockStore()])
        intelligence_layer = IntelligenceLayer(agents=agents)
        output_layer = OutputLayer(generators=outputs)

        pipeline = data_layer | intelligence_layer | output_layer

        # Execute
        result = pipeline.invoke({})

        # Verify output
        self.assertIn("generated_outputs", result)
        self.assertEqual(len(result["generated_outputs"]), 2)


class TestCreateWorkflow(unittest.TestCase):
    """Test create_workflow helper."""

    def test_create_workflow_all_layers(self):
        """Test create_workflow with all layers."""
        source = MockSource("test")
        store = MockStore()
        agent = MockAgent("test")
        generator = MockGenerator("pdf")

        wf = create_workflow(
            data_sources=source, data_stores=[store], agents=agent, generators=generator
        )

        # Should be a chainable
        from openbench.core import Chainable

        self.assertIsInstance(wf, Chainable)

        # Should execute successfully
        result = wf.invoke({})
        self.assertIsNotNone(result)

    def test_create_workflow_partial(self):
        """Test create_workflow with partial layers."""
        agent = MockAgent("test")
        generator = MockGenerator("pdf")

        # Only intelligence and output layers
        wf = create_workflow(agents=agent, generators=generator)

        result = wf.invoke({})
        self.assertIsNotNone(result)

    def test_create_workflow_empty_raises(self):
        """Test create_workflow with no layers raises error."""
        with self.assertRaises(ValueError):
            create_workflow()


if __name__ == "__main__":
    unittest.main()
