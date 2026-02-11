"""Intelligence Layer - Agentic Workflows."""

# L2 Orchestrator (use this for workflow composition)
from openbench.core.layers import IntelligenceLayer

# Pre-built agent types (extend BaseAgent)
from openbench.intelligence.agents import (
    ActionAgent,
    AnalysisAgent,
    ContentAgent,
    MetaAgent,
    ResearchAgent,
)

# Base agent classes and utilities
from openbench.intelligence.base import (
    AgentConfig,
    AgentMemory,
    BaseAgent,
    Message,
    MessageRole,
    SimpleAgent,
    StructuredOutputAgent,
    ToolExecutor,
)

# Embedding providers
from openbench.intelligence.embeddings import (
    EMBEDDING_PROVIDERS,
    GoogleEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
    register_model,
    register_provider,
    resolve_embedding_provider,
)

# Agent Factory (convenience class for creating agents)
from openbench.intelligence.layer import AgentFactory

# LLM providers
from openbench.intelligence.llm_providers import GeminiLLMProvider

__all__ = [
    # L2 Orchestrator
    "IntelligenceLayer",
    # Factory
    "AgentFactory",
    # Pre-built agents
    "ResearchAgent",
    "AnalysisAgent",
    "ContentAgent",
    "ActionAgent",
    "MetaAgent",
    # Base agent classes
    "BaseAgent",
    "SimpleAgent",
    "StructuredOutputAgent",
    # Agent utilities
    "AgentMemory",
    "AgentConfig",
    "ToolExecutor",
    "Message",
    "MessageRole",
    # LLM providers
    "GeminiLLMProvider",
    # Embedding providers
    "OpenAIEmbeddingProvider",
    "GoogleEmbeddingProvider",
    "get_embedding_provider",
    "resolve_embedding_provider",
    "register_model",
    "register_provider",
    "EMBEDDING_PROVIDERS",
]
