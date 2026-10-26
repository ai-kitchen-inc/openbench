"""
Enhanced Plugin Registry for OpenBench.

Provides a dynamic, decorator-based plugin system with:
- Generic type support for type safety
- Decorator-based registration (@registry.register)
- Auto-discovery from packages
- Plugin metadata (version, description, author)
- Singleton pattern support
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Type variable for plugin base classes
T = TypeVar("T")


@dataclass
class PluginMetadata:
    """Metadata for a registered plugin."""

    name: str
    plugin_type: str
    provider: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    registered_at: datetime = field(default_factory=datetime.now)

    # Runtime info
    class_name: str = ""
    module_name: str = ""

    @property
    def key(self) -> str:
        """Unique key for this plugin."""
        return f"{self.plugin_type}:{self.provider}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "plugin_type": self.plugin_type,
            "provider": self.provider,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "registered_at": self.registered_at.isoformat(),
            "class_name": self.class_name,
            "module_name": self.module_name,
        }


@dataclass
class PluginEntry(Generic[T]):
    """Entry in the plugin registry."""

    implementation: type[T]
    metadata: PluginMetadata
    singleton_instance: T | None = None
    is_singleton: bool = False


class PluginRegistry(Generic[T]):
    """
    Generic plugin registry with decorator-based registration.

    This is the core registry class that all specific registries extend.
    It provides:
    - Decorator-based registration
    - Auto-discovery from packages
    - Plugin metadata support
    - Singleton pattern support
    - Type-safe plugin creation

    Example:
        >>> # Create a registry for LLM adapters
        >>> LLMRegistry = PluginRegistry[LLMProvider]("llm")
        >>>
        >>> # Register with decorator
        >>> @LLMRegistry.register("chat", "openai", description="OpenAI Chat API")
        ... class OpenAIChatAdapter(LLMProvider):
        ...     pass
        >>>
        >>> # Create instance
        >>> adapter = LLMRegistry.create("chat", "openai", api_key="...")
        >>>
        >>> # List plugins
        >>> LLMRegistry.list_plugins()
        ['chat:openai']
    """

    # Class-level storage for all registry instances
    _all_registries: dict[str, PluginRegistry] = {}

    def __init__(self, name: str, base_class: type[T] | None = None):
        """
        Initialize a plugin registry.

        Args:
            name: Registry name (e.g., 'llm', 'vector', 'output')
            base_class: Optional base class that all plugins must inherit from
        """
        self.name = name
        self.base_class = base_class
        self._plugins: dict[str, PluginEntry[T]] = {}
        self._discovery_paths: list[str] = []

        # Register this registry globally
        PluginRegistry._all_registries[name] = self

    def register(
        self,
        plugin_type: str,
        provider: str = "default",
        *,
        version: str = "1.0.0",
        description: str = "",
        author: str = "",
        tags: list[str] | None = None,
        singleton: bool = False,
        override: bool = False,
    ) -> Callable[[type[T]], type[T]]:
        """
        Decorator to register a plugin implementation.

        Args:
            plugin_type: Type of plugin (e.g., 'pdf', 'research', 'vector')
            provider: Provider name (e.g., 'openai', 'pinecone', 'default')
            version: Plugin version
            description: Plugin description
            author: Plugin author
            tags: Tags for categorization
            singleton: If True, create only one instance
            override: If True, allow overriding existing registration

        Returns:
            Decorator function

        Example:
            >>> @DataSourceRegistry.register("pdf", "pdfplumber",
            ...                              description="PDF extraction using pdfplumber")
            ... class PDFPlumberSource(DataSource):
            ...     pass
        """

        def decorator(cls: type[T]) -> type[T]:
            key = f"{plugin_type}:{provider}"

            # Check if already registered
            if key in self._plugins and not override:
                existing = self._plugins[key]
                logger.warning(
                    f"Plugin '{key}' already registered as {existing.metadata.class_name}. "
                    f"Use override=True to replace."
                )
                return cls

            # Validate base class if specified
            if self.base_class is not None and not issubclass(cls, self.base_class):
                raise TypeError(
                    f"Plugin {cls.__name__} must inherit from {self.base_class.__name__}"
                )

            # Create metadata
            metadata = PluginMetadata(
                name=cls.__name__,
                plugin_type=plugin_type,
                provider=provider,
                version=version,
                description=description or cls.__doc__ or "",
                author=author,
                tags=tags or [],
                class_name=cls.__name__,
                module_name=cls.__module__,
            )

            # Create entry
            entry = PluginEntry(
                implementation=cls,
                metadata=metadata,
                is_singleton=singleton,
            )

            self._plugins[key] = entry

            logger.debug(f"Registered plugin: {key} -> {cls.__name__}")

            return cls

        return decorator

    def register_class(
        self,
        plugin_type: str,
        provider: str,
        implementation: type[T],
        **metadata_kwargs,
    ) -> None:
        """
        Programmatically register a plugin class.

        This is the non-decorator version for dynamic registration.

        Args:
            plugin_type: Type of plugin
            provider: Provider name
            implementation: Plugin class
            **metadata_kwargs: Additional metadata (version, description, etc.)

        Example:
            >>> DataSourceRegistry.register_class('pdf', 'pdfplumber', PDFPlumberSource)
        """
        decorator = self.register(plugin_type, provider, **metadata_kwargs)
        decorator(implementation)

    def get(
        self,
        plugin_type: str,
        provider: str = "default",
    ) -> type[T] | None:
        """
        Get a registered plugin class.

        Args:
            plugin_type: Type of plugin
            provider: Provider name

        Returns:
            Plugin class or None if not found
        """
        key = f"{plugin_type}:{provider}"
        entry = self._plugins.get(key)
        return entry.implementation if entry else None

    def get_metadata(
        self,
        plugin_type: str,
        provider: str = "default",
    ) -> PluginMetadata | None:
        """
        Get metadata for a registered plugin.

        Args:
            plugin_type: Type of plugin
            provider: Provider name

        Returns:
            PluginMetadata or None if not found
        """
        key = f"{plugin_type}:{provider}"
        entry = self._plugins.get(key)
        return entry.metadata if entry else None

    def create(
        self,
        plugin_type: str,
        provider: str = "default",
        **kwargs,
    ) -> T:
        """
        Create an instance of a registered plugin.

        Args:
            plugin_type: Type of plugin
            provider: Provider name
            **kwargs: Arguments to pass to plugin constructor

        Returns:
            Plugin instance

        Raises:
            ValueError: If plugin not found
            TypeError: If instantiation fails

        Example:
            >>> source = DataSourceRegistry.create('pdf', 'pdfplumber', path='./doc.pdf')
        """
        key = f"{plugin_type}:{provider}"
        entry = self._plugins.get(key)

        if not entry:
            available = self.list_providers(plugin_type)
            raise ValueError(
                f"Plugin not found: {key}. "
                f"Available providers for '{plugin_type}': {available or 'none'}"
            )

        # Return singleton if configured
        if entry.is_singleton:
            if entry.singleton_instance is None:
                entry.singleton_instance = entry.implementation(**kwargs)
            return entry.singleton_instance

        # Create new instance
        try:
            return entry.implementation(**kwargs)
        except TypeError as e:
            raise TypeError(
                f"Failed to instantiate {entry.implementation.__name__}: {e}. "
                f"Check constructor arguments."
            ) from e

    def list_types(self) -> list[str]:
        """
        List all registered plugin types.

        Returns:
            List of plugin type names
        """
        return sorted({key.split(":", 1)[0] for key in self._plugins})

    def list_providers(self, plugin_type: str) -> list[str]:
        """
        List all providers for a given plugin type.

        Args:
            plugin_type: Type of plugin

        Returns:
            List of provider names
        """
        prefix = f"{plugin_type}:"
        return sorted(key.split(":", 1)[1] for key in self._plugins if key.startswith(prefix))

    def list_plugins(
        self,
        plugin_type: str | None = None,
        tags: list[str] | None = None,
    ) -> list[str]:
        """
        List all registered plugins.

        Args:
            plugin_type: Filter by plugin type
            tags: Filter by tags (plugin must have all specified tags)

        Returns:
            List of plugin keys (format: "type:provider")
        """
        result = []
        for key, entry in self._plugins.items():
            # Filter by type
            if plugin_type:
                entry_type, _ = key.split(":", 1)
                if entry_type != plugin_type:
                    continue

            # Filter by tags
            if tags and not all(tag in entry.metadata.tags for tag in tags):
                continue

            result.append(key)

        return sorted(result)

    def get_all_metadata(
        self,
        plugin_type: str | None = None,
    ) -> list[PluginMetadata]:
        """
        Get metadata for all registered plugins.

        Args:
            plugin_type: Filter by plugin type

        Returns:
            List of PluginMetadata objects
        """
        result = []
        for key, entry in self._plugins.items():
            if plugin_type:
                entry_type, _ = key.split(":", 1)
                if entry_type != plugin_type:
                    continue
            result.append(entry.metadata)
        return result

    def is_registered(self, plugin_type: str, provider: str) -> bool:
        """
        Check if a plugin is registered.

        Args:
            plugin_type: Type of plugin
            provider: Provider name

        Returns:
            True if registered
        """
        key = f"{plugin_type}:{provider}"
        return key in self._plugins

    def unregister(self, plugin_type: str, provider: str) -> bool:
        """
        Unregister a plugin.

        Args:
            plugin_type: Type of plugin
            provider: Provider name

        Returns:
            True if unregistered, False if not found
        """
        key = f"{plugin_type}:{provider}"
        if key in self._plugins:
            del self._plugins[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all registered plugins."""
        self._plugins.clear()

    def auto_discover(self, package: str) -> int:
        """
        Auto-discover and load plugins from a package.

        Imports all modules in the package, triggering any @register decorators.

        Args:
            package: Package path (e.g., 'openbench.plugins.llm')

        Returns:
            Number of modules loaded

        Example:
            >>> LLMRegistry.auto_discover('openbench.plugins.llm')
            3  # Loaded 3 modules
        """
        count = 0
        try:
            pkg = importlib.import_module(package)
        except ImportError as e:
            logger.warning(f"Failed to import package {package}: {e}")
            return 0

        if not hasattr(pkg, "__path__"):
            logger.warning(f"{package} is not a package")
            return 0

        for _, name, is_pkg in pkgutil.iter_modules(pkg.__path__):
            try:
                module_name = f"{package}.{name}"
                importlib.import_module(module_name)
                count += 1
                logger.debug(f"Auto-discovered module: {module_name}")

                # Recursively discover sub-packages
                if is_pkg:
                    count += self.auto_discover(module_name)
            except ImportError as e:
                logger.warning(f"Failed to import {package}.{name}: {e}")

        return count

    def discover_from_path(self, path: str | Path) -> int:
        """
        Discover plugins from a filesystem path.

        Useful for loading plugins from external directories.

        Args:
            path: Directory path containing plugin modules

        Returns:
            Number of plugins loaded
        """
        path = Path(path)
        if not path.is_dir():
            logger.warning(f"Not a directory: {path}")
            return 0

        count = 0
        for file in path.glob("*.py"):
            if file.name.startswith("_"):
                continue

            try:
                spec = importlib.util.spec_from_file_location(file.stem, file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    count += 1
                    logger.debug(f"Loaded plugin from: {file}")
            except Exception as e:
                logger.warning(f"Failed to load {file}: {e}")

        return count

    def __repr__(self) -> str:
        return f"PluginRegistry(name={self.name!r}, plugins={len(self._plugins)})"

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, key: str) -> bool:
        return key in self._plugins

    @classmethod
    def get_registry(cls, name: str) -> PluginRegistry | None:
        """Get a registry by name."""
        return cls._all_registries.get(name)

    @classmethod
    def list_registries(cls) -> list[str]:
        """List all registered registries."""
        return list(cls._all_registries.keys())


# ============================================================================
# Pre-defined Registries for OpenBench Core Abstractions
# ============================================================================

# Import base classes for registry type constraints.
# Placed after PluginRegistry definition to avoid circular import
# (abstractions.py imports from chainable.py which is independent of registry).
from openbench.core.abstractions import (  # noqa: E402
    Agent,
    DataSource,
    DataStore,
    LLMProvider,
    OutputGenerator,
    Tool,
    TranscriptionProvider,
    VLMProvider,
)

# Create typed registries
DataSourceRegistry = PluginRegistry[DataSource]("data_source", DataSource)
DataStoreRegistry = PluginRegistry[DataStore]("data_store", DataStore)
AgentRegistry = PluginRegistry[Agent]("agent", Agent)
LLMProviderRegistry = PluginRegistry[LLMProvider]("llm_provider", LLMProvider)
TranscriptionRegistry = PluginRegistry[TranscriptionProvider](
    "transcription_provider", TranscriptionProvider
)
VLMProviderRegistry = PluginRegistry[VLMProvider]("vlm_provider", VLMProvider)
ToolRegistry = PluginRegistry[Tool]("tool", Tool)
OutputGeneratorRegistry = PluginRegistry[OutputGenerator]("output_generator", OutputGenerator)


# ============================================================================
# Convenience Functions
# ============================================================================


def register_all(registrations: dict[str, list[tuple]]) -> int:
    """
    Register multiple implementations at once.

    Args:
        registrations: Dict mapping registry names to registration configs
            Format: {
                'data_source': [
                    (type, provider, class, metadata_dict),
                ],
                ...
            }

            metadata_dict keys: version, description, author, tags, singleton

    Returns:
        Number of plugins registered

    Example:
        >>> register_all({
        ...     'data_source': [
        ...         ('pdf', 'pdfplumber', PDFPlumberSource, {
        ...             'description': 'PDF extraction using pdfplumber',
        ...             'version': '1.0.0'
        ...         }),
        ...     ],
        ...     'llm_provider': [
        ...         ('llm', 'openai', OpenAIProvider, {}),
        ...     ]
        ... })
    """
    count = 0
    for registry_name, items in registrations.items():
        registry = PluginRegistry.get_registry(registry_name)
        if registry is None:
            raise ValueError(
                f"Unknown registry: {registry_name}. Available: {PluginRegistry.list_registries()}"
            )

        for item_type, provider, implementation, metadata in items:
            registry.register_class(item_type, provider, implementation, **metadata)
            count += 1

    return count


def discover_plugins(packages: list[str] | None = None) -> dict[str, int]:
    """
    Auto-discover plugins from specified packages.

    Args:
        packages: List of package paths to discover from.
                  If None, discovers from default openbench plugin paths.

    Returns:
        Dict mapping registry names to number of plugins discovered

    Example:
        >>> discover_plugins(['openbench.plugins.llm', 'openbench.plugins.output'])
        {'llm': 3, 'output': 2}
    """
    if packages is None:
        packages = [
            "openbench.plugins.data_sources",
            "openbench.plugins.data_stores",
            "openbench.plugins.agents",
            "openbench.plugins.llm",
            "openbench.plugins.tools",
            "openbench.plugins.output",
        ]

    results: dict[str, int] = {}
    for package in packages:
        # Find matching registry
        for name, registry in PluginRegistry._all_registries.items():
            try:
                count = registry.auto_discover(package)
                results[name] = results.get(name, 0) + count
            except Exception as e:
                logger.debug(f"Could not discover from {package}: {e}")

    return results


def get_plugin_info() -> dict[str, list[dict[str, Any]]]:
    """
    Get information about all registered plugins.

    Returns:
        Dict mapping registry names to lists of plugin metadata

    Example:
        >>> info = get_plugin_info()
        >>> for name, plugins in info.items():
        ...     print(f"{name}: {len(plugins)} plugins")
    """
    result = {}
    for name, registry in PluginRegistry._all_registries.items():
        result[name] = [m.to_dict() for m in registry.get_all_metadata()]
    return result
