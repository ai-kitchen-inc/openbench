"""Core abstractions and interfaces for OpenBench."""

from openbench.core.abstractions import (
    DataSource,
    DataStore,
    Agent,
    FrameworkAdapter,
    LLMProvider,
    Tool,
    OutputGenerator,
    RawData,
    Query,
    SearchResult,
    ExecutionContext,
    ExecutionResult,
    LLMResponse,
    GeneratedOutput,
)

from openbench.core.registry import (
    # Core registry class
    PluginRegistry,
    PluginMetadata,
    PluginEntry,
    # Pre-defined registries
    DataSourceRegistry,
    DataStoreRegistry,
    AgentRegistry,
    LLMProviderRegistry,
    ToolRegistry,
    OutputGeneratorRegistry,
    # Utility functions
    register_all,
    discover_plugins,
    get_plugin_info,
)

from openbench.core.chainable import (
    Chainable,
    Chain,
    Parallel,
    Conditional,
    Router,
    Lambda,
    Passthrough,
    RunnableConfig,
)

from openbench.core.state import (
    WorkflowState,
    WorkflowStatus,
    StateStore,
    LocalStateStore,
    StatefulChainable,
    StepRecord,
)

from openbench.core.layers import (
    DataLayer,
    IntelligenceLayer,
    OutputLayer,
    create_workflow,
)

from openbench.core.providers import (
    ProviderType,
    ProviderConfig,
    ProviderService,
    CredentialEncryption,
    get_provider_service,
    get_credential_encryption,
    reset_provider_service,
    configure_provider,
    resolve_provider,
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

__all__ = [
    # Abstractions
    "DataSource",
    "DataStore",
    "Agent",
    "FrameworkAdapter",
    "LLMProvider",
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
