"""Tests for enhanced plugin registry pattern."""

import unittest
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
from openbench.core.registry import (
    AgentRegistry,
    DataSourceRegistry,
    DataStoreRegistry,
    LLMProviderRegistry,
    OutputGeneratorRegistry,
    PluginMetadata,
    PluginRegistry,
    ToolRegistry,
    get_plugin_info,
    register_all,
)

# ============================================================================
# Test implementations
# ============================================================================


class TestPDFSource(DataSource):
    """Test PDF data source implementation."""

    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "pdf"

    @property
    def source_id(self) -> str:
        return f"pdf:{self.path}"

    def get_metadata(self) -> dict[str, Any]:
        return {"path": self.path}

    def extract(self) -> RawData:
        return RawData("content", "text", {}, self)

    def validate(self) -> bool:
        return True


class TestVectorStore(DataStore):
    """Test vector store implementation."""

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

    def get(self, item_id: str) -> Any | None:
        return next((item for item in self._data if item["id"] == item_id), None)

    def delete(self, item_id: str) -> bool:
        return True

    def update(self, item_id: str, data: Any) -> bool:
        return True


class TestAgent(Agent):
    """Test agent implementation."""

    def __init__(self, goal: str):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "test"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output={"result": "success"}, status="completed", metadata={}, cost=0.0
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class TestLLMProvider(LLMProvider):
    """Test LLM provider implementation."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "test"

    def generate(self, prompt: str, model: str, **params) -> LLMResponse:
        return LLMResponse("response", model, 10, 0.0)


class TestTool(Tool):
    """Test tool implementation."""

    @property
    def name(self) -> str:
        return "test_tool"

    @property
    def description(self) -> str:
        return "Test tool"

    def execute(self, **params) -> Any:
        return {}

    def get_schema(self) -> dict[str, Any]:
        return {}


class TestGenerator(OutputGenerator):
    """Test output generator implementation."""

    @property
    def output_format(self) -> str:
        return "test"

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        return GeneratedOutput("/tmp/test.txt", "test", 100, {})

    def validate(self, content: Any) -> bool:
        return True


# ============================================================================
# Test Cases
# ============================================================================


class TestPluginRegistryBasic(unittest.TestCase):
    """Test basic PluginRegistry functionality."""

    def setUp(self):
        """Clear registries before each test."""
        DataSourceRegistry.clear()
        DataStoreRegistry.clear()
        AgentRegistry.clear()
        LLMProviderRegistry.clear()
        ToolRegistry.clear()
        OutputGeneratorRegistry.clear()

    def test_register_class_method(self):
        """Test programmatic registration with register_class."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)

        self.assertTrue(DataSourceRegistry.is_registered("pdf", "test"))
        self.assertFalse(DataSourceRegistry.is_registered("pdf", "other"))

    def test_create_instance(self):
        """Test creating instance from registry."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)

        source = DataSourceRegistry.create("pdf", "test", path="./test.pdf")
        self.assertIsInstance(source, TestPDFSource)
        self.assertEqual(source.path, "./test.pdf")

    def test_list_types(self):
        """Test listing registered types."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)
        DataSourceRegistry.register_class("csv", "test", TestPDFSource)

        types = DataSourceRegistry.list_types()
        self.assertIn("pdf", types)
        self.assertIn("csv", types)

    def test_list_providers(self):
        """Test listing providers for a type."""
        DataSourceRegistry.register_class("pdf", "provider1", TestPDFSource)
        DataSourceRegistry.register_class("pdf", "provider2", TestPDFSource)

        providers = DataSourceRegistry.list_providers("pdf")
        self.assertEqual(len(providers), 2)
        self.assertIn("provider1", providers)
        self.assertIn("provider2", providers)

    def test_unknown_type_raises_error(self):
        """Test that unknown type raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            DataSourceRegistry.create("unknown", "test")

        self.assertIn("Plugin not found", str(ctx.exception))

    def test_unknown_provider_raises_error(self):
        """Test that unknown provider raises ValueError."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)

        with self.assertRaises(ValueError) as ctx:
            DataSourceRegistry.create("pdf", "unknown")

        self.assertIn("Plugin not found", str(ctx.exception))
        self.assertIn("test", str(ctx.exception))  # Should suggest available providers


class TestPluginRegistryDecorator(unittest.TestCase):
    """Test decorator-based registration."""

    def setUp(self):
        """Clear registries before each test."""
        DataSourceRegistry.clear()

    def test_decorator_registration(self):
        """Test registration via decorator."""

        @DataSourceRegistry.register("pdf", "decorated")
        class DecoratedPDFSource(DataSource):
            def __init__(self, path: str):
                self.path = path

            @property
            def source_type(self) -> str:
                return "pdf"

            @property
            def source_id(self) -> str:
                return f"pdf:{self.path}"

            def get_metadata(self) -> dict[str, Any]:
                return {}

            def extract(self) -> RawData:
                return RawData("content", "text", {}, self)

            def validate(self) -> bool:
                return True

        # Should be registered
        self.assertTrue(DataSourceRegistry.is_registered("pdf", "decorated"))

        # Should be able to create
        source = DataSourceRegistry.create("pdf", "decorated", path="test.pdf")
        self.assertIsInstance(source, DecoratedPDFSource)

    def test_decorator_with_metadata(self):
        """Test decorator with metadata parameters."""

        @DataSourceRegistry.register(
            "pdf",
            "with_meta",
            version="2.0.0",
            description="PDF source with metadata",
            author="Test Author",
            tags=["pdf", "document"],
        )
        class MetaPDFSource(DataSource):
            def __init__(self, path: str):
                self.path = path

            @property
            def source_type(self) -> str:
                return "pdf"

            @property
            def source_id(self) -> str:
                return f"pdf:{self.path}"

            def get_metadata(self) -> dict[str, Any]:
                return {}

            def extract(self) -> RawData:
                return RawData("content", "text", {}, self)

            def validate(self) -> bool:
                return True

        # Get metadata
        metadata = DataSourceRegistry.get_metadata("pdf", "with_meta")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.version, "2.0.0")
        self.assertEqual(metadata.description, "PDF source with metadata")
        self.assertEqual(metadata.author, "Test Author")
        self.assertIn("pdf", metadata.tags)


class TestPluginRegistryMetadata(unittest.TestCase):
    """Test plugin metadata functionality."""

    def setUp(self):
        """Clear registries before each test."""
        DataSourceRegistry.clear()

    def test_get_metadata(self):
        """Test retrieving plugin metadata."""
        DataSourceRegistry.register_class(
            "pdf",
            "test",
            TestPDFSource,
            version="1.5.0",
            description="Test PDF source",
        )

        metadata = DataSourceRegistry.get_metadata("pdf", "test")
        self.assertIsInstance(metadata, PluginMetadata)
        self.assertEqual(metadata.plugin_type, "pdf")
        self.assertEqual(metadata.provider, "test")
        self.assertEqual(metadata.version, "1.5.0")

    def test_get_all_metadata(self):
        """Test getting all metadata."""
        DataSourceRegistry.register_class("pdf", "test1", TestPDFSource)
        DataSourceRegistry.register_class("pdf", "test2", TestPDFSource)
        DataSourceRegistry.register_class("csv", "test", TestPDFSource)

        # All metadata
        all_meta = DataSourceRegistry.get_all_metadata()
        self.assertEqual(len(all_meta), 3)

        # Filtered by type
        pdf_meta = DataSourceRegistry.get_all_metadata("pdf")
        self.assertEqual(len(pdf_meta), 2)

    def test_metadata_to_dict(self):
        """Test metadata serialization."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)

        metadata = DataSourceRegistry.get_metadata("pdf", "test")
        data = metadata.to_dict()

        self.assertIn("name", data)
        self.assertIn("plugin_type", data)
        self.assertIn("provider", data)
        self.assertIn("version", data)
        self.assertIn("registered_at", data)


class TestPluginRegistrySingleton(unittest.TestCase):
    """Test singleton pattern support."""

    def setUp(self):
        """Clear registries before each test."""
        LLMProviderRegistry.clear()

    def test_singleton_returns_same_instance(self):
        """Test that singleton returns same instance."""

        @LLMProviderRegistry.register("llm", "singleton_test", singleton=True)
        class SingletonProvider(LLMProvider):
            def __init__(self, api_key: str = "default"):
                self.api_key = api_key

            @property
            def provider_name(self) -> str:
                return "singleton"

            def generate(self, prompt: str, model: str, **params) -> LLMResponse:
                return LLMResponse("response", model, 10, 0.0)

        # Create twice
        instance1 = LLMProviderRegistry.create("llm", "singleton_test", api_key="key1")
        instance2 = LLMProviderRegistry.create("llm", "singleton_test", api_key="key2")

        # Should be same instance
        self.assertIs(instance1, instance2)
        # Should have first key (singleton ignores subsequent kwargs)
        self.assertEqual(instance1.api_key, "key1")

    def test_non_singleton_returns_different_instances(self):
        """Test that non-singleton returns different instances."""
        LLMProviderRegistry.register_class("llm", "non_singleton", TestLLMProvider)

        instance1 = LLMProviderRegistry.create("llm", "non_singleton", api_key="key1")
        instance2 = LLMProviderRegistry.create("llm", "non_singleton", api_key="key2")

        # Should be different instances
        self.assertIsNot(instance1, instance2)
        self.assertEqual(instance1.api_key, "key1")
        self.assertEqual(instance2.api_key, "key2")


class TestPluginRegistryFiltering(unittest.TestCase):
    """Test filtering and listing functionality."""

    def setUp(self):
        """Clear and populate registry."""
        DataSourceRegistry.clear()
        DataSourceRegistry.register_class(
            "pdf", "provider1", TestPDFSource, tags=["document", "text"]
        )
        DataSourceRegistry.register_class(
            "pdf", "provider2", TestPDFSource, tags=["document", "ocr"]
        )
        DataSourceRegistry.register_class("csv", "default", TestPDFSource, tags=["data", "tabular"])

    def test_list_plugins_all(self):
        """Test listing all plugins."""
        plugins = DataSourceRegistry.list_plugins()
        self.assertEqual(len(plugins), 3)

    def test_list_plugins_by_type(self):
        """Test filtering plugins by type."""
        pdf_plugins = DataSourceRegistry.list_plugins(plugin_type="pdf")
        self.assertEqual(len(pdf_plugins), 2)
        self.assertIn("pdf:provider1", pdf_plugins)
        self.assertIn("pdf:provider2", pdf_plugins)

    def test_list_plugins_by_tags(self):
        """Test filtering plugins by tags."""
        doc_plugins = DataSourceRegistry.list_plugins(tags=["document"])
        self.assertEqual(len(doc_plugins), 2)

        ocr_plugins = DataSourceRegistry.list_plugins(tags=["document", "ocr"])
        self.assertEqual(len(ocr_plugins), 1)


class TestPluginRegistryUnregister(unittest.TestCase):
    """Test unregistration functionality."""

    def setUp(self):
        """Clear registries."""
        DataSourceRegistry.clear()

    def test_unregister(self):
        """Test unregistering a plugin."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)
        self.assertTrue(DataSourceRegistry.is_registered("pdf", "test"))

        result = DataSourceRegistry.unregister("pdf", "test")
        self.assertTrue(result)
        self.assertFalse(DataSourceRegistry.is_registered("pdf", "test"))

    def test_unregister_nonexistent(self):
        """Test unregistering non-existent plugin."""
        result = DataSourceRegistry.unregister("pdf", "nonexistent")
        self.assertFalse(result)

    def test_clear(self):
        """Test clearing all plugins."""
        DataSourceRegistry.register_class("pdf", "test1", TestPDFSource)
        DataSourceRegistry.register_class("pdf", "test2", TestPDFSource)
        self.assertEqual(len(DataSourceRegistry), 2)

        DataSourceRegistry.clear()
        self.assertEqual(len(DataSourceRegistry), 0)


class TestPluginRegistryTypeValidation(unittest.TestCase):
    """Test base class validation."""

    def setUp(self):
        """Clear registries."""
        DataSourceRegistry.clear()

    def test_invalid_base_class_raises_error(self):
        """Test that invalid base class raises TypeError."""

        class NotADataSource:
            pass

        with self.assertRaises(TypeError) as ctx:

            @DataSourceRegistry.register("pdf", "invalid")
            class InvalidSource(NotADataSource):
                pass

        self.assertIn("must inherit from", str(ctx.exception))


class TestRegisterAll(unittest.TestCase):
    """Test bulk registration function."""

    def setUp(self):
        """Clear registries."""
        DataSourceRegistry.clear()
        DataStoreRegistry.clear()
        AgentRegistry.clear()

    def test_register_all_basic(self):
        """Test basic bulk registration."""
        registrations = {
            "data_source": [
                ("pdf", "test", TestPDFSource, {}),
            ],
            "data_store": [
                ("vector", "test", TestVectorStore, {}),
            ],
            "agent": [
                ("test", "default", TestAgent, {}),
            ],
        }

        count = register_all(registrations)
        self.assertEqual(count, 3)

        self.assertTrue(DataSourceRegistry.is_registered("pdf", "test"))
        self.assertTrue(DataStoreRegistry.is_registered("vector", "test"))
        self.assertTrue(AgentRegistry.is_registered("test", "default"))

    def test_register_all_with_metadata(self):
        """Test bulk registration with metadata."""
        registrations = {
            "data_source": [
                (
                    "pdf",
                    "with_meta",
                    TestPDFSource,
                    {"description": "Test PDF", "version": "2.0.0"},
                ),
            ],
        }

        register_all(registrations)

        metadata = DataSourceRegistry.get_metadata("pdf", "with_meta")
        self.assertEqual(metadata.description, "Test PDF")
        self.assertEqual(metadata.version, "2.0.0")

    def test_register_all_unknown_registry(self):
        """Test that unknown registry raises error."""
        registrations = {
            "unknown_registry": [
                ("test", "test", TestPDFSource, {}),
            ],
        }

        with self.assertRaises(ValueError) as ctx:
            register_all(registrations)

        self.assertIn("Unknown registry", str(ctx.exception))


class TestGetPluginInfo(unittest.TestCase):
    """Test get_plugin_info function."""

    def setUp(self):
        """Clear and populate registries."""
        DataSourceRegistry.clear()
        LLMProviderRegistry.clear()

        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)
        LLMProviderRegistry.register_class("llm", "test", TestLLMProvider)

    def test_get_plugin_info(self):
        """Test getting info for all plugins."""
        info = get_plugin_info()

        self.assertIn("data_source", info)
        self.assertIn("llm_provider", info)

        # Check data source info
        ds_info = info["data_source"]
        self.assertEqual(len(ds_info), 1)
        self.assertEqual(ds_info[0]["plugin_type"], "pdf")


class TestPluginRegistryContains(unittest.TestCase):
    """Test __contains__ and __len__ methods."""

    def setUp(self):
        """Clear registries."""
        DataSourceRegistry.clear()

    def test_len(self):
        """Test __len__."""
        self.assertEqual(len(DataSourceRegistry), 0)

        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)
        self.assertEqual(len(DataSourceRegistry), 1)

    def test_contains(self):
        """Test __contains__."""
        DataSourceRegistry.register_class("pdf", "test", TestPDFSource)

        self.assertIn("pdf:test", DataSourceRegistry)
        self.assertNotIn("pdf:other", DataSourceRegistry)


class TestPluginRegistryGlobalAccess(unittest.TestCase):
    """Test global registry access."""

    def test_get_registry_by_name(self):
        """Test getting registry by name."""
        registry = PluginRegistry.get_registry("data_source")
        self.assertIs(registry, DataSourceRegistry)

    def test_list_registries(self):
        """Test listing all registries."""
        registries = PluginRegistry.list_registries()
        self.assertIn("data_source", registries)
        self.assertIn("agent", registries)
        self.assertIn("llm_provider", registries)


if __name__ == "__main__":
    unittest.main()
