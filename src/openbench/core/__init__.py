"""Core abstractions and interfaces for OpenBench."""

# isort: skip_file
# ChatLayer must be imported after all core modules to avoid circular imports.

from openbench.core.abstractions import (
    Agent,
    DataSource,
    DataStore,
    ExecutionContext,
    ExecutionResult,
    FrameworkAdapter,
    GeneratedOutput,
    LLMProvider,
    LLMResponse,
    MediaContent,
    OutputGenerator,
    Query,
    RawData,
    SearchResult,
    Tool,
)
from openbench.core.chainable import (
    Chain,
    Chainable,
    ChainExecutionError,
    Conditional,
    Lambda,
    Parallel,
    Passthrough,
    Router,
    RunnableConfig,
)
from openbench.core.config import (
    Config,
    ModelInfo,
    get_config,
    get_default_model,
    reset_config,
)
from openbench.core.context import (
    ProjectContext,
    ProjectRegistry,
    generate_project_id,
    get_project_registry,
    reset_project_registry,
)
from openbench.core.layers import (
    DataLayer,
    IntelligenceLayer,
    OutputLayer,
    create_workflow,
)
from openbench.core.providers import (
    CredentialEncryption,
    ProviderConfig,
    ProviderService,
    ProviderType,
    configure_provider,
    get_credential_encryption,
    get_provider_service,
    reset_provider_service,
    resolve_provider,
)
from openbench.core.registry import (
    AgentRegistry,
    # Pre-defined registries
    DataSourceRegistry,
    DataStoreRegistry,
    LLMProviderRegistry,
    OutputGeneratorRegistry,
    PluginEntry,
    PluginMetadata,
    # Core registry class
    PluginRegistry,
    ToolRegistry,
    discover_plugins,
    get_plugin_info,
    # Utility functions
    register_all,
)
from openbench.core.state import (
    LocalStateStore,
    StatefulChainable,
    StateStore,
    StepRecord,
    WorkflowState,
    WorkflowStatus,
)
from openbench.chat.layer import ChatLayer

__all__ = [
    # Abstractions
    "DataSource",
    "DataStore",
    "Agent",
    "FrameworkAdapter",
    "LLMProvider",
    "MediaContent",
    "Tool",
    "OutputGenerator",
    "RawData",
    "Query",
    "SearchResult",
    "ExecutionContext",
    "ExecutionResult",
    "LLMResponse",
    "GeneratedOutput",
    # Registries
    "PluginRegistry",
    "PluginMetadata",
    "PluginEntry",
    "DataSourceRegistry",
    "DataStoreRegistry",
    "AgentRegistry",
    "LLMProviderRegistry",
    "ToolRegistry",
    "OutputGeneratorRegistry",
    "register_all",
    "discover_plugins",
    "get_plugin_info",
    # Chainable
    "Chainable",
    "Chain",
    "ChainExecutionError",
    "Parallel",
    "Conditional",
    "Router",
    "Lambda",
    "Passthrough",
    "RunnableConfig",
    # State
    "WorkflowState",
    "WorkflowStatus",
    "StateStore",
    "LocalStateStore",
    "StatefulChainable",
    "StepRecord",
    # Layers (L2)
    "DataLayer",
    "IntelligenceLayer",
    "OutputLayer",
    "ChatLayer",
    "create_workflow",
    # Providers
    "ProviderType",
    "ProviderConfig",
    "ProviderService",
    "CredentialEncryption",
    "get_provider_service",
    "get_credential_encryption",
    "reset_provider_service",
    "configure_provider",
    "resolve_provider",
    # Config
    "Config",
    "ModelInfo",
    "get_config",
    "get_default_model",
    "reset_config",
    # Context
    "ProjectContext",
    "ProjectRegistry",
    "generate_project_id",
    "get_project_registry",
    "reset_project_registry",
]
