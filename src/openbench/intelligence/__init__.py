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
    ProgressEvent,
    QueryRewriter,
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

# VLM providers and vision agent
from openbench.intelligence.vlm_providers import GeminiVLMProvider, GemmaVLMProvider
from openbench.intelligence.vision import VisionAgent, extract_image_inputs

# Memory (persistent conversation memory)
from openbench.intelligence.memory import (
    LocalSQLiteMemoryStore,
    MemoryStore,
    PersistentMemory,
    SQLiteMemoryStore,
)

# Persona Layer (file-based agent identity)
from openbench.intelligence.persona import Persona

# Planning (task decomposition)
from openbench.intelligence.planning import TaskPlan, TaskPlanner

# Skill Layer (two-tier capability packages)
from openbench.intelligence.skill import Skill
from openbench.intelligence.skill_registry import SkillRegistry

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
    "ProgressEvent",
    "QueryRewriter",
    "ToolExecutor",
    "Message",
    "MessageRole",
    # LLM providers
    "GeminiLLMProvider",
    # VLM providers
    "GeminiVLMProvider",
    "GemmaVLMProvider",
    # Vision agents
    "VisionAgent",
    "extract_image_inputs",
    # Persona Layer
    "Persona",
    # Skill Layer
    "Skill",
    "SkillRegistry",
    # Memory
    "MemoryStore",
    "PersistentMemory",
    "SQLiteMemoryStore",
    "LocalSQLiteMemoryStore",
    # Planning
    "TaskPlan",
    "TaskPlanner",
    # Embedding providers
    "OpenAIEmbeddingProvider",
    "GoogleEmbeddingProvider",
    "get_embedding_provider",
    "resolve_embedding_provider",
    "register_model",
    "register_provider",
    "EMBEDDING_PROVIDERS",
]
