"""
Registry pattern implementations for all OpenBench abstractions.

Allows users to register and create implementations dynamically.
"""

from typing import Any, Dict, Type, Optional, List
from openbench.core.abstractions import (
    DataSource,
    DataStore,
    Agent,
    LLMProvider,
    Tool,
    OutputGenerator,
)


class RegistryBase:
    """Base class for all registries."""

    _registry: Dict[str, Dict[str, Type[Any]]] = {}

    @classmethod
    def register(
        cls,
        item_type: str,
        provider: str,
        implementation: Type[Any]
    ) -> None:
        """
        Register an implementation.

        Args:
            item_type: Type of item (e.g., 'vector', 'research')
            provider: Provider name (e.g., 'pinecone', 'openai')
            implementation: Implementation class
        """
        if item_type not in cls._registry:
            cls._registry[item_type] = {}
        cls._registry[item_type][provider] = implementation

    @classmethod
    def create(
        cls,
        item_type: str,
        provider: str,
        **config
    ) -> Any:
        """
        Create an instance of a registered implementation.

        Args:
            item_type: Type of item
            provider: Provider name
            **config: Configuration parameters for the implementation

        Returns:
            Instance of the implementation

        Raises:
            ValueError: If type or provider not found
        """
        if item_type not in cls._registry:
            raise ValueError(
                f"Unknown {cls.__name__} type: {item_type}. "
                f"Available: {list(cls._registry.keys())}"
            )

        if provider not in cls._registry[item_type]:
            raise ValueError(
                f"Unknown provider '{provider}' for {item_type}. "
                f"Available: {list(cls._registry[item_type].keys())}"
            )

        implementation = cls._registry[item_type][provider]
        return implementation(**config)

    @classmethod
    def list_types(cls) -> List[str]:
        """List all registered types."""
        return list(cls._registry.keys())

    @classmethod
    def list_providers(cls, item_type: str) -> List[str]:
        """List all providers for a given type."""
        if item_type not in cls._registry:
            return []
        return list(cls._registry[item_type].keys())

    @classmethod
    def is_registered(cls, item_type: str, provider: str) -> bool:
        """Check if a provider is registered for a type."""
        return (
            item_type in cls._registry and
            provider in cls._registry[item_type]
        )


class DataSourceRegistry(RegistryBase):
    """
    Registry for DataSource implementations.

    Example:
        >>> # Register implementation
        >>> DataSourceRegistry.register('pdf', 'pdfplumber', PDFPlumberSource)
        >>>
        >>> # Create instance
        >>> source = DataSourceRegistry.create('pdf', 'pdfplumber', path='./doc.pdf')
        >>>
        >>> # List available
        >>> DataSourceRegistry.list_types()
        ['pdf', 'youtube', 'web', 'google_doc']
        >>> DataSourceRegistry.list_providers('pdf')
        ['pdfplumber', 'pypdf2']
    """
    _registry: Dict[str, Dict[str, Type[DataSource]]] = {}


class DataStoreRegistry(RegistryBase):
    """
    Registry for DataStore implementations.

    Example:
        >>> # Register implementations
        >>> DataStoreRegistry.register('vector', 'pinecone', PineconeStore)
        >>> DataStoreRegistry.register('vector', 'chroma', ChromaStore)
        >>>
        >>> # Create instance - user chooses provider
        >>> store = DataStoreRegistry.create(
        ...     'vector',
        ...     'pinecone',  # User choice!
        ...     api_key='...',
        ...     index_name='my-index'
        ... )
        >>>
        >>> # Switch to different provider - just change provider param
        >>> store = DataStoreRegistry.create(
        ...     'vector',
        ...     'chroma',  # Different provider
        ...     path='./chroma_db'
        ... )
    """
    _registry: Dict[str, Dict[str, Type[DataStore]]] = {}


class AgentRegistry(RegistryBase):
    """
    Registry for Agent implementations.

    Example:
        >>> # Register agent types
        >>> AgentRegistry.register('research', 'default', ResearchAgent)
        >>> AgentRegistry.register('analysis', 'default', AnalysisAgent)
        >>>
        >>> # Create agents
        >>> researcher = AgentRegistry.create(
        ...     'research',
        ...     'default',
        ...     goal='Analyze sustainability trends'
        ... )
        >>>
        >>> # List available
        >>> AgentRegistry.list_types()
        ['research', 'analysis', 'content', 'critic']
    """
    _registry: Dict[str, Dict[str, Type[Agent]]] = {}


class LLMProviderRegistry(RegistryBase):
    """
    Registry for LLM Provider implementations.

    Example:
        >>> # Register providers
        >>> LLMProviderRegistry.register('llm', 'openai', OpenAIProvider)
        >>> LLMProviderRegistry.register('llm', 'anthropic', AnthropicProvider)
        >>>
        >>> # Create instance - user chooses provider
        >>> llm = LLMProviderRegistry.create(
        ...     'llm',
        ...     'openai',  # User choice
        ...     api_key='...'
        ... )
        >>>
        >>> # Easy to switch providers
        >>> llm = LLMProviderRegistry.create(
        ...     'llm',
        ...     'anthropic',  # Just change this
        ...     api_key='...'
        ... )
    """
    _registry: Dict[str, Dict[str, Type[LLMProvider]]] = {}


class ToolRegistry(RegistryBase):
    """
    Registry for Tool implementations.

    Example:
        >>> # Register tools
        >>> ToolRegistry.register('search', 'tavily', TavilySearchTool)
        >>> ToolRegistry.register('search', 'serp', SerpAPITool)
        >>> ToolRegistry.register('mcp', 'filesystem', FilesystemMCP)
        >>>
        >>> # Create tools
        >>> search = ToolRegistry.create('search', 'tavily', api_key='...')
        >>> mcp = ToolRegistry.create('mcp', 'filesystem', base_path='./data')
        >>>
        >>> # List available
        >>> ToolRegistry.list_types()
        ['search', 'calculator', 'mcp']
        >>> ToolRegistry.list_providers('search')
        ['tavily', 'serp', 'duckduckgo']
    """
    _registry: Dict[str, Dict[str, Type[Tool]]] = {}


class OutputGeneratorRegistry(RegistryBase):
    """
    Registry for OutputGenerator implementations.

    Example:
        >>> # Register generators
        >>> OutputGeneratorRegistry.register('pdf', 'reportlab', ReportLabGenerator)
        >>> OutputGeneratorRegistry.register('pdf', 'weasyprint', WeasyPrintGenerator)
        >>> OutputGeneratorRegistry.register('pptx', 'python-pptx', PythonPPTXGenerator)
        >>>
        >>> # Create generator - user chooses provider
        >>> pdf_gen = OutputGeneratorRegistry.create(
        ...     'pdf',
        ...     'reportlab',  # User choice
        ...     template='corporate'
        ... )
        >>>
        >>> # Easy to switch
        >>> pdf_gen = OutputGeneratorRegistry.create(
        ...     'pdf',
        ...     'weasyprint',  # Different provider
        ...     template='corporate'
        ... )
        >>>
        >>> # List available
        >>> OutputGeneratorRegistry.list_types()
        ['pdf', 'pptx', 'html', 'audio', 'video']
        >>> OutputGeneratorRegistry.list_providers('pdf')
        ['reportlab', 'weasyprint', 'pdfkit']
    """
    _registry: Dict[str, Dict[str, Type[OutputGenerator]]] = {}


# Convenience function for bulk registration
def register_all(registrations: Dict[str, Any]) -> None:
    """
    Register multiple implementations at once.

    Args:
        registrations: Dict mapping registry names to registration configs

    Example:
        >>> register_all({
        ...     'data_sources': [
        ...         ('pdf', 'pdfplumber', PDFPlumberSource),
        ...         ('youtube', 'default', YouTubeSource),
        ...     ],
        ...     'data_stores': [
        ...         ('vector', 'pinecone', PineconeStore),
        ...         ('vector', 'chroma', ChromaStore),
        ...     ],
        ...     'llm_providers': [
        ...         ('llm', 'openai', OpenAIProvider),
        ...         ('llm', 'anthropic', AnthropicProvider),
        ...     ]
        ... })
    """
    registry_map = {
        'data_sources': DataSourceRegistry,
        'data_stores': DataStoreRegistry,
        'agents': AgentRegistry,
        'llm_providers': LLMProviderRegistry,
        'tools': ToolRegistry,
        'output_generators': OutputGeneratorRegistry,
    }

    for registry_name, items in registrations.items():
        if registry_name not in registry_map:
            raise ValueError(f"Unknown registry: {registry_name}")

        registry = registry_map[registry_name]
        for item_type, provider, implementation in items:
            registry.register(item_type, provider, implementation)
