"""Tests for registry pattern."""

import unittest
from typing import Any, Dict, Optional

from openbench.core.abstractions import (
    DataSource,
    RawData,
    DataStore,
    Query,
    SearchResult,
    Agent,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    LLMResponse,
    Tool,
    OutputGenerator,
    GeneratedOutput,
)
from openbench.core.registry import (
    DataSourceRegistry,
    DataStoreRegistry,
    AgentRegistry,
    LLMProviderRegistry,
    ToolRegistry,
    OutputGeneratorRegistry,
    register_all,
)


# Test implementations
class TestPDFSource(DataSource):
    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "pdf"

    @property
    def source_id(self) -> str:
        return f"pdf:{self.path}"

    def get_metadata(self) -> Dict[str, Any]:
        return {"path": self.path}

    def extract(self) -> RawData:
        return RawData("content", "text", {}, self)

    def validate(self) -> bool:
        return True


class TestVectorStore(DataStore):
    def __init__(self, collection: str):
        self.collection = collection
        self._data = []

    @property
    def store_type(self) -> str:
        return "vector"

    def index(self, data: RawData, **options) -> str:
        item_id = f"item_{len(self._data)}"
        self._data.append({"id": item_id, "data": data})
        return item_id

    def search(self, query: Query) -> SearchResult:
        return SearchResult(items=self._data, total=len(self._data))

    def get(self, item_id: str) -> Optional[Any]:
        return next((item for item in self._data if item["id"] == item_id), None)

    def delete(self, item_id: str) -> bool:
        return True

    def update(self, item_id: str, data: Any) -> bool:
        return True


class TestAgent(Agent):
    def __init__(self, goal: str):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "test"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output={"result": "success"},
            status="completed",
            metadata={},
            cost=0.0
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class TestLLMProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "test"

    def generate(self, prompt: str, model: str, **params) -> LLMResponse:
        return LLMResponse("response", model, 10, 0.0)

    def embed(self, text: str, model: Optional[str] = None):
        return [0.1, 0.2, 0.3]


class TestTool(Tool):
    @property
    def name(self) -> str:
        return "test_tool"

    @property
    def description(self) -> str:
        return "Test tool"

    def execute(self, **params) -> Any:
        return {}

    def get_schema(self) -> Dict[str, Any]:
        return {}


class TestGenerator(OutputGenerator):
    @property
    def output_format(self) -> str:
        return "test"

    def generate(self, content: Any, template: Optional[str] = None, **options) -> GeneratedOutput:
        return GeneratedOutput("/tmp/test.txt", "test", 100, {})

    def validate(self, content: Any) -> bool:
        return True


class TestRegistry(unittest.TestCase):
    """Test registry pattern."""

    def setUp(self):
        """Clear registries before each test."""
        # Clear all registries
        DataSourceRegistry._registry = {}
        DataStoreRegistry._registry = {}
        AgentRegistry._registry = {}
        LLMProviderRegistry._registry = {}
        ToolRegistry._registry = {}
        OutputGeneratorRegistry._registry = {}

    def test_data_source_registry(self):
        """Test DataSourceRegistry."""
        # Register
        DataSourceRegistry.register('pdf', 'test', TestPDFSource)

        # Check registration
        self.assertTrue(DataSourceRegistry.is_registered('pdf', 'test'))
        self.assertFalse(DataSourceRegistry.is_registered('pdf', 'other'))

        # Create instance
        source = DataSourceRegistry.create('pdf', 'test', path='./test.pdf')
        self.assertIsInstance(source, TestPDFSource)
        self.assertEqual(source.path, './test.pdf')

        # List types and providers
        types = DataSourceRegistry.list_types()
        self.assertIn('pdf', types)

        providers = DataSourceRegistry.list_providers('pdf')
        self.assertIn('test', providers)

    def test_data_store_registry(self):
        """Test DataStoreRegistry."""
        # Register
        DataStoreRegistry.register('vector', 'test', TestVectorStore)

        # Create instance
        store = DataStoreRegistry.create('vector', 'test', collection='test_collection')
        self.assertIsInstance(store, TestVectorStore)
        self.assertEqual(store.collection, 'test_collection')

    def test_agent_registry(self):
        """Test AgentRegistry."""
        # Register
        AgentRegistry.register('test', 'default', TestAgent)

        # Create instance
        agent = AgentRegistry.create('test', 'default', goal='test goal')
        self.assertIsInstance(agent, TestAgent)
        self.assertEqual(agent.goal, 'test goal')

    def test_llm_provider_registry(self):
        """Test LLMProviderRegistry."""
        # Register
        LLMProviderRegistry.register('llm', 'test', TestLLMProvider)

        # Create instance
        provider = LLMProviderRegistry.create('llm', 'test', api_key='test_key')
        self.assertIsInstance(provider, TestLLMProvider)
        self.assertEqual(provider.api_key, 'test_key')

    def test_tool_registry(self):
        """Test ToolRegistry."""
        # Register
        ToolRegistry.register('test', 'default', TestTool)

        # Create instance
        tool = ToolRegistry.create('test', 'default')
        self.assertIsInstance(tool, TestTool)

    def test_output_generator_registry(self):
        """Test OutputGeneratorRegistry."""
        # Register
        OutputGeneratorRegistry.register('test', 'default', TestGenerator)

        # Create instance
        generator = OutputGeneratorRegistry.create('test', 'default')
        self.assertIsInstance(generator, TestGenerator)

    def test_unknown_type_raises_error(self):
        """Test that unknown type raises ValueError."""
        with self.assertRaises(ValueError):
            DataSourceRegistry.create('unknown', 'test')

    def test_unknown_provider_raises_error(self):
        """Test that unknown provider raises ValueError."""
        DataSourceRegistry.register('pdf', 'test', TestPDFSource)

        with self.assertRaises(ValueError):
            DataSourceRegistry.create('pdf', 'unknown')

    def test_register_all(self):
        """Test bulk registration."""
        registrations = {
            'data_sources': [
                ('pdf', 'test', TestPDFSource),
            ],
            'data_stores': [
                ('vector', 'test', TestVectorStore),
            ],
            'agents': [
                ('test', 'default', TestAgent),
            ],
        }

        register_all(registrations)

        # Verify all registered
        self.assertTrue(DataSourceRegistry.is_registered('pdf', 'test'))
        self.assertTrue(DataStoreRegistry.is_registered('vector', 'test'))
        self.assertTrue(AgentRegistry.is_registered('test', 'default'))

    def test_registry_isolation(self):
        """Test that registries are independent."""
        DataSourceRegistry.register('pdf', 'test', TestPDFSource)
        DataStoreRegistry.register('vector', 'test', TestVectorStore)

        # Each registry should only have its own types
        self.assertEqual(DataSourceRegistry.list_types(), ['pdf'])
        self.assertEqual(DataStoreRegistry.list_types(), ['vector'])

    def test_multiple_providers_same_type(self):
        """Test multiple providers for same type."""
        # Register two providers
        DataSourceRegistry.register('pdf', 'provider1', TestPDFSource)
        DataSourceRegistry.register('pdf', 'provider2', TestPDFSource)

        providers = DataSourceRegistry.list_providers('pdf')
        self.assertEqual(len(providers), 2)
        self.assertIn('provider1', providers)
        self.assertIn('provider2', providers)

        # Can create with either provider
        source1 = DataSourceRegistry.create('pdf', 'provider1', path='test.pdf')
        source2 = DataSourceRegistry.create('pdf', 'provider2', path='test.pdf')

        self.assertIsInstance(source1, TestPDFSource)
        self.assertIsInstance(source2, TestPDFSource)


if __name__ == "__main__":
    unittest.main()
