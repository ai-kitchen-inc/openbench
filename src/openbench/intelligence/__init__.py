"""Intelligence Layer - Agentic Workflows."""

# L2 Orchestrator (use this for workflow composition)
from openbench.core.layers import IntelligenceLayer

# Agent Factory (convenience class for creating agents)
from openbench.intelligence.layer import AgentFactory

# Pre-built agent types (extend BaseAgent)
from openbench.intelligence.agents import (
    ResearchAgent,
    AnalysisAgent,
    ContentAgent,
    ActionAgent,
    MetaAgent,
)

# Base agent classes and utilities
from openbench.intelligence.base import (
    BaseAgent,
    SimpleAgent,
    StructuredOutputAgent,
    AgentMemory,
    AgentConfig,
    ToolExecutor,
    Message,
    MessageRole,
)

# LLM providers
from openbench.intelligence.llm_providers import GeminiLLMProvider

# Embedding providers
from openbench.intelligence.embeddings import (
    OpenAIEmbeddingProvider,
    GoogleEmbeddingProvider,
    get_embedding_provider,
    resolve_embedding_provider,
    EMBEDDING_PROVIDERS,
)

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
    "EMBEDDING_PROVIDERS",
]
