"""
Intelligence Layer - Agent Factory and Helpers.

NOTE: For L2 workflow orchestration, use IntelligenceLayer from openbench.core.layers.
This module provides factory functions for creating agents.
"""

from typing import Any, List, Optional


class AgentFactory:
    """
    Factory for creating AI agents.

    Provides convenient methods for creating and configuring agents.
    For L2 workflow orchestration, use IntelligenceLayer from core.layers.

    Examples:
        >>> # Create a simple agent
        >>> agent = AgentFactory.create(
        ...     goal="Analyze Q4 sales data",
        ...     agent_type="research",
        ...     model="gpt-4o"
        ... )
        >>>
        >>> # Execute agent
        >>> result = agent.execute(context)
    """

    @classmethod
    def create(
        cls,
        goal: str,
        agent_type: str = "base",
        tools: Optional[List[Any]] = None,
        model: str = "gpt-4o",
        **kwargs
    ) -> Any:
        """
        Create an AI agent.

        Args:
            goal: Agent's objective
            agent_type: Type of agent (base, simple, structured, research, analysis, content)
            tools: List of tools available to the agent
            model: LLM model to use
            **kwargs: Additional agent configuration

        Returns:
            Configured agent instance
        """
        from openbench.intelligence.base import BaseAgent, SimpleAgent, StructuredOutputAgent
        from openbench.intelligence.agents import (
            ResearchAgent,
            AnalysisAgent,
            ContentAgent,
            ActionAgent,
            MetaAgent,
        )

        agent_classes = {
            "base": BaseAgent,
            "simple": SimpleAgent,
            "structured": StructuredOutputAgent,
            "research": ResearchAgent,
            "analysis": AnalysisAgent,
            "content": ContentAgent,
            "action": ActionAgent,
            "meta": MetaAgent,
        }

        agent_class = agent_classes.get(agent_type, BaseAgent)

        # Handle structured agent separately (needs output_schema)
        if agent_type == "structured":
            output_schema = kwargs.pop("output_schema", {"type": "object"})
            return agent_class(goal=goal, output_schema=output_schema, tools=tools, model=model, **kwargs)

        return agent_class(goal=goal, tools=tools, model=model, **kwargs)

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
