"""
Intelligence Layer - Agent Factory and Helpers.

NOTE: For L2 workflow orchestration, use IntelligenceLayer from openbench.core.layers.
This module provides factory functions for creating agents.

Agents are registered with AgentRegistry for dynamic discovery and extensibility.
"""

from typing import Any, List, Optional

from openbench.core.registry import AgentRegistry


def _register_builtin_agents() -> None:
    """Register all built-in agent types with AgentRegistry."""
    from openbench.intelligence.base import BaseAgent, SimpleAgent, StructuredOutputAgent
    from openbench.intelligence.agents import (
        ResearchAgent,
        AnalysisAgent,
        ContentAgent,
        ActionAgent,
        MetaAgent,
    )

    # Register base agents
    AgentRegistry.register_class(
        "base", "default", BaseAgent,
        description="Framework-agnostic base agent with tool support"
    )
    AgentRegistry.register_class(
        "simple", "default", SimpleAgent,
        description="Simple agent without tool use"
    )
    AgentRegistry.register_class(
        "structured", "default", StructuredOutputAgent,
        description="Agent that outputs structured JSON data"
    )

    # Register specialized agents
    AgentRegistry.register_class(
        "research", "default", ResearchAgent,
        description="Agent specialized in gathering and synthesizing information"
    )
    AgentRegistry.register_class(
        "analysis", "default", AnalysisAgent,
        description="Agent specialized in data analysis and insights"
    )
    AgentRegistry.register_class(
        "content", "default", ContentAgent,
        description="Agent specialized in content generation"
    )
    AgentRegistry.register_class(
        "action", "default", ActionAgent,
        description="Agent specialized in executing actions and integrations"
    )
    AgentRegistry.register_class(
        "meta", "default", MetaAgent,
        description="Agent that coordinates other agents"
    )


# Register built-in agents when module is imported
_register_builtin_agents()


class AgentFactory:
    """
    Factory for creating AI agents.

    Uses AgentRegistry for dynamic agent discovery and creation.
    Custom agents can be registered with AgentRegistry and created via this factory.

    Examples:
        >>> # Create a simple agent (uses config default model)
        >>> agent = AgentFactory.create(
        ...     goal="Analyze Q4 sales data",
        ...     agent_type="research"
        ... )
        >>>
        >>> # Execute agent
        >>> result = agent.execute(context)
        >>>
        >>> # Register and use custom agent
        >>> from openbench.core import AgentRegistry
        >>> AgentRegistry.register_class("custom", "myteam", MyCustomAgent)
        >>> agent = AgentFactory.create(goal="...", agent_type="custom", provider="myteam")
    """

    @classmethod
    def create(
        cls,
        goal: str,
        agent_type: str = "base",
        provider: str = "default",
        tools: Optional[List[Any]] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Create an AI agent.

        Args:
            goal: Agent's objective
            agent_type: Type of agent (base, simple, structured, research, analysis, content, action, meta)
            provider: Provider/implementation name (default: "default")
            tools: List of tools available to the agent
            model: LLM model to use (defaults to config llm.default_model)
            **kwargs: Additional agent configuration

        Returns:
            Configured agent instance

        Raises:
            ValueError: If agent_type is not registered
        """
        # Handle structured agent separately (needs output_schema)
        if agent_type == "structured":
            output_schema = kwargs.pop("output_schema", {"type": "object"})
            return AgentRegistry.create(
                agent_type, provider,
                goal=goal, output_schema=output_schema, tools=tools, model=model, **kwargs
            )

        return AgentRegistry.create(
            agent_type, provider,
            goal=goal, tools=tools, model=model, **kwargs
        )

    @classmethod
    def research(cls, goal: str, **kwargs) -> Any:
        """Create a research agent."""
        return cls.create(goal=goal, agent_type="research", **kwargs)

    @classmethod
    def analysis(cls, goal: str, **kwargs) -> Any:
        """Create an analysis agent."""
        return cls.create(goal=goal, agent_type="analysis", **kwargs)

    @classmethod
    def content(cls, goal: str, **kwargs) -> Any:
        """Create a content agent."""
        return cls.create(goal=goal, agent_type="content", **kwargs)

    @classmethod
    def simple(cls, goal: str, **kwargs) -> Any:
        """Create a simple agent (no tools)."""
        return cls.create(goal=goal, agent_type="simple", **kwargs)

    @classmethod
    def action(cls, goal: str, **kwargs) -> Any:
        """Create an action agent."""
        return cls.create(goal=goal, agent_type="action", **kwargs)

    @classmethod
    def meta(cls, goal: str, **kwargs) -> Any:
        """Create a meta agent (orchestrator)."""
        return cls.create(goal=goal, agent_type="meta", **kwargs)

    @classmethod
    def list_types(cls) -> List[str]:
        """List all registered agent types."""
        return AgentRegistry.list_types()

    @classmethod
    def list_providers(cls, agent_type: str) -> List[str]:
        """List all providers for a given agent type."""
        return AgentRegistry.list_providers(agent_type)

    @classmethod
    def register(
        cls,
        agent_type: str,
        provider: str,
        agent_class: type,
        description: str = "",
        **metadata
    ) -> None:
        """
        Register a custom agent type.

        Args:
            agent_type: Type identifier (e.g., "custom", "specialized")
            provider: Provider/implementation name
            agent_class: Agent class (must inherit from BaseAgent or Agent)
            description: Description of the agent
            **metadata: Additional metadata (version, author, tags)

        Example:
            >>> class MyAgent(BaseAgent):
            ...     pass
            >>> AgentFactory.register("custom", "myteam", MyAgent, "Custom agent for my team")
            >>> agent = AgentFactory.create(goal="...", agent_type="custom", provider="myteam")
        """
        AgentRegistry.register_class(agent_type, provider, agent_class, description=description, **metadata)
