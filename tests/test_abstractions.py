"""Tests for core abstractions."""

import unittest
from datetime import datetime
from typing import Any

from openbench.core.abstractions import (
    Agent,
    DataSource,
    DataStore,
    ExecutionContext,
    ExecutionResult,
    GeneratedOutput,
    LLMProvider,
    LLMResponse,
    OutputGenerator,
    Query,
    RawData,
    SearchResult,
    Tool,
)


# Mock implementations for testing
class MockDataSource(DataSource):
    """Mock data source for testing."""

    def __init__(self, source_id: str = "test"):
        self._source_id = source_id

    @property
    def source_type(self) -> str:
        return "mock"

    @property
    def source_id(self) -> str:
        return self._source_id

    def get_metadata(self) -> dict[str, Any]:
        return {"type": "mock", "id": self._source_id}

    def extract(self) -> RawData:
        return RawData(
            content="test content", content_type="text", metadata=self.get_metadata(), source=self
        )

    def validate(self) -> bool:
        return True


class MockDataStore(DataStore):
    """Mock data store for testing."""

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
        return SearchResult(items=self._data[: query.limit], total=len(self._data))

    def get(self, item_id: str) -> Any | None:
        return next((item for item in self._data if item["id"] == item_id), None)

    def delete(self, item_id: str) -> bool:
        self._data = [item for item in self._data if item["id"] != item_id]
        return True

    def update(self, item_id: str, data: Any) -> bool:
        for item in self._data:
            if item["id"] == item_id:
                item["data"] = data
                return True
        return False


class MockAgent(Agent):
    """Mock agent for testing."""

    def __init__(self, goal: str = "test"):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output={"result": "success"},
            status="completed",
            metadata={"goal": context.goal},
            cost=0.0,
            tokens_used=0,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(self, prompt: str, model: str, **params) -> LLMResponse:
        return LLMResponse(text=f"Response to: {prompt}", model=model, tokens_used=10, cost=0.0)


class MockTool(Tool):
    """Mock tool for testing."""

    @property
    def name(self) -> str:
        return "mock_tool"

    @property
    def description(self) -> str:
        return "A mock tool for testing"

    def execute(self, **params) -> Any:
        return {"result": "success"}

    def get_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}


class MockOutputGenerator(OutputGenerator):
    """Mock output generator for testing."""

    @property
    def output_format(self) -> str:
        return "mock"

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        return GeneratedOutput(
            file_path="/tmp/test.mock",
            format="mock",
            size_bytes=100,
            metadata={"template": template},
        )

    def validate(self, content: Any) -> bool:
        return True


class TestAbstractions(unittest.TestCase):
    """Test core abstractions."""

    def test_data_source_interface(self):
        """Test DataSource interface."""
        source = MockDataSource("test-source")

        self.assertEqual(source.source_type, "mock")
        self.assertEqual(source.source_id, "test-source")
        self.assertTrue(source.validate())

        metadata = source.get_metadata()
        self.assertIn("type", metadata)
        self.assertIn("id", metadata)

        data = source.extract()
        self.assertIsInstance(data, RawData)
        self.assertEqual(data.content, "test content")

    def test_data_source_chainable(self):
        """Test DataSource is Chainable."""
        source = MockDataSource()

        # Should have invoke method
        result = source.invoke()
        self.assertIsInstance(result, RawData)

    def test_raw_data(self):
        """Test RawData container."""
        source = MockDataSource()
        data = RawData(
            content="test", content_type="text", metadata={"key": "value"}, source=source
        )

        self.assertEqual(data.content, "test")
        self.assertEqual(data.content_type, "text")
        self.assertEqual(data.metadata["key"], "value")
        self.assertIsInstance(data.extracted_at, datetime)

    def test_query(self):
        """Test Query object."""
        query = Query(
            text="test query", vector=[0.1, 0.2], filters={"category": "test"}, limit=5, offset=0
        )

        self.assertEqual(query.text, "test query")
        self.assertEqual(query.limit, 5)
        self.assertEqual(query.filters["category"], "test")

    def test_search_result(self):
        """Test SearchResult object."""
        result = SearchResult(
            items=[{"id": 1}, {"id": 2}], total=10, scores=[0.9, 0.8], metadata={"query": "test"}
        )

        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.total, 10)
        self.assertEqual(len(result.scores), 2)

    def test_data_store_interface(self):
        """Test DataStore interface."""
        store = MockDataStore()

        self.assertEqual(store.store_type, "mock")

        # Test indexing
        data = RawData("test", "text", {})
        item_id = store.index(data)
        self.assertIsNotNone(item_id)

        # Test retrieval
        retrieved = store.get(item_id)
        self.assertIsNotNone(retrieved)

        # Test search
        query = Query(text="test", limit=10)
        results = store.search(query)
        self.assertIsInstance(results, SearchResult)

        # Test update
        updated = store.update(item_id, "new data")
        self.assertTrue(updated)

        # Test delete
        deleted = store.delete(item_id)
        self.assertTrue(deleted)

    def test_execution_context(self):
        """Test ExecutionContext."""
        context = ExecutionContext(
            goal="test goal",
            data={"key": "value"},
            tools=[],
            memory=None,
            constraints={"timeout": 60},
        )

        self.assertEqual(context.goal, "test goal")
        self.assertEqual(context.data["key"], "value")
        self.assertEqual(context.constraints["timeout"], 60)

    def test_execution_result(self):
        """Test ExecutionResult."""
        result = ExecutionResult(
            output={"result": "success"},
            status="completed",
            metadata={"agent": "test"},
            cost=0.05,
            tokens_used=100,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.cost, 0.05)
        self.assertEqual(result.tokens_used, 100)

    def test_agent_interface(self):
        """Test Agent interface."""
        agent = MockAgent("test goal")

        self.assertEqual(agent.agent_type, "mock")
        self.assertEqual(agent.goal, "test goal")

        context = ExecutionContext(goal="test", data=None)
        result = agent.execute(context)

        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.status, "completed")

        cost = agent.estimate_cost(context)
        self.assertIsInstance(cost, float)

    def test_agent_chainable(self):
        """Test Agent is Chainable."""
        agent = MockAgent()

        # Should have invoke method
        result = agent.invoke({})
        self.assertIsInstance(result, ExecutionResult)

    def test_llm_provider_interface(self):
        """Test LLMProvider interface."""
        provider = MockLLMProvider()

        self.assertEqual(provider.provider_name, "mock")

        response = provider.generate("test prompt", "gpt-4")
        self.assertIsInstance(response, LLMResponse)
        self.assertIn("test prompt", response.text)

    def test_llm_response(self):
        """Test LLMResponse."""
        response = LLMResponse(
            text="test response",
            model="gpt-4",
            tokens_used=50,
            cost=0.001,
            metadata={"temperature": 0.7},
        )

        self.assertEqual(response.text, "test response")
        self.assertEqual(response.model, "gpt-4")
        self.assertEqual(response.tokens_used, 50)

    def test_tool_interface(self):
        """Test Tool interface."""
        tool = MockTool()

        self.assertEqual(tool.name, "mock_tool")
        self.assertIsInstance(tool.description, str)

        result = tool.execute(param="value")
        self.assertIsInstance(result, dict)

        schema = tool.get_schema()
        self.assertIn("type", schema)

    def test_generated_output(self):
        """Test GeneratedOutput."""
        output = GeneratedOutput(
            file_path="/tmp/test.pdf",
            format="pdf",
            size_bytes=1024,
            metadata={"template": "corporate"},
        )

        self.assertEqual(output.file_path, "/tmp/test.pdf")
        self.assertEqual(output.format, "pdf")
        self.assertIsInstance(output.generated_at, datetime)

        # Test serialization
        output_dict = output.to_dict()
        self.assertIn("file_path", output_dict)
        self.assertIn("format", output_dict)

        # Test deserialization
        restored = GeneratedOutput.from_dict(output_dict)
        self.assertEqual(restored.file_path, output.file_path)

    def test_output_generator_interface(self):
        """Test OutputGenerator interface."""
        generator = MockOutputGenerator()

        self.assertEqual(generator.output_format, "mock")

        output = generator.generate({"content": "test"})
        self.assertIsInstance(output, GeneratedOutput)

        valid = generator.validate({"content": "test"})
        self.assertTrue(valid)

    def test_output_generator_chainable(self):
        """Test OutputGenerator is Chainable."""
        generator = MockOutputGenerator()

        # Should have invoke method
        result = generator.invoke({"content": "test"})
        self.assertIsInstance(result, GeneratedOutput)


if __name__ == "__main__":
    unittest.main()
