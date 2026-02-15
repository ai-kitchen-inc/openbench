"""Pre-built agent types extending BaseAgent."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult, Tool

if TYPE_CHECKING:
    from collections.abc import Callable
from openbench.intelligence.base import BaseAgent

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    """Agent specialized in gathering and synthesizing information."""

    def __init__(
        self,
        goal: str,
        sources: list[str] | None = None,
        depth: str = "standard",
        tools: list[Tool | Callable] | None = None,
        model: str | None = None,
        **kwargs,
    ):
        # Build research-specific system prompt
        system_prompt = f"""You are a research agent with the goal: {goal}

Your task is to gather and synthesize information from available sources.
Research depth: {depth}
Available sources: {", ".join(sources) if sources else "all"}

Approach:
1. Identify key information needs
2. Search and gather relevant data
3. Synthesize findings into coherent insights
4. Cite sources when possible"""

        super().__init__(goal=goal, tools=tools, model=model, system_prompt=system_prompt, **kwargs)
        self.sources = sources or ["all"]
        self.depth = depth

    @property
    def agent_type(self) -> str:
        return "research"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with research-specific pre/post processing."""
        # Pre-processing: auto-retrieve from store per source
        if self.store and self.sources:
            for source in self.sources:
                if source != "all":
                    self._retrieve_context(f"{context.goal} {source}")

        result = super().execute(context)

        # Post-processing: enrich metadata
        if result.output:
            result.metadata["sources_used"] = self.sources
            result.metadata["depth"] = self.depth
        return result


class AnalysisAgent(BaseAgent):
    """Agent specialized in data analysis and insights."""

    def __init__(
        self,
        goal: str,
        methods: list[str] | None = None,
        tools: list[Tool | Callable] | None = None,
        model: str | None = None,
        **kwargs,
    ):
        methods_list = methods or ["statistical", "trend_detection"]
        system_prompt = f"""You are an analysis agent with the goal: {goal}

Your task is to analyze data and extract meaningful insights.
Analysis methods: {", ".join(methods_list)}

Approach:
1. Understand the data structure and context
2. Apply appropriate analysis methods
3. Identify patterns, trends, and anomalies
4. Provide actionable insights with supporting evidence"""

        super().__init__(goal=goal, tools=tools, model=model, system_prompt=system_prompt, **kwargs)
        self.methods = methods_list

    @property
    def agent_type(self) -> str:
        return "analysis"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with analysis-specific pre/post processing."""
        # Pre-processing: inject analysis methods into context data
        if self.methods:
            data = context.data if isinstance(context.data, dict) else {}
            data["analysis_methods"] = self.methods
            context = ExecutionContext(
                goal=context.goal,
                data=data,
                tools=context.tools,
                memory=context.memory,
                constraints=context.constraints,
            )

        result = super().execute(context)

        # Post-processing: enrich metadata
        if result.output:
            result.metadata["methods"] = self.methods
        return result


class ContentAgent(BaseAgent):
    """Agent specialized in content generation."""

    def __init__(
        self,
        goal: str,
        style: str = "professional",
        length: str | None = None,
        tools: list[Tool | Callable] | None = None,
        model: str | None = None,
        **kwargs,
    ):
        length_instruction = (
            f"Target length: {length}" if length else "Appropriate length for the content type"
        )
        system_prompt = f"""You are a content generation agent with the goal: {goal}

Your task is to create high-quality content.
Writing style: {style}
{length_instruction}

Guidelines:
1. Understand the audience and purpose
2. Structure content clearly
3. Use engaging and appropriate language
4. Ensure accuracy and clarity"""

        super().__init__(goal=goal, tools=tools, model=model, system_prompt=system_prompt, **kwargs)
        self.style = style
        self.length = length

    @property
    def agent_type(self) -> str:
        return "content"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute with content-specific post processing."""
        result = super().execute(context)

        # Post-processing: enrich metadata
        if result.output:
            result.metadata["style"] = self.style
            if self.length:
                result.metadata["target_length"] = self.length
        return result


class ActionAgent(BaseAgent):
    """Agent specialized in executing actions and integrations."""

    def __init__(
        self,
        goal: str,
        actions: list[dict] | None = None,
        tools: list[Tool | Callable] | None = None,
        model: str | None = None,
        **kwargs,
    ):
        actions_desc = "\n".join(
            [f"- {a.get('name', 'action')}: {a.get('description', '')}" for a in (actions or [])]
        )
        system_prompt = f"""You are an action agent with the goal: {goal}

Your task is to execute actions and integrations.
{f"Available actions:{chr(10)}{actions_desc}" if actions_desc else "Use available tools to complete tasks."}

Approach:
1. Plan the sequence of actions needed
2. Execute each action carefully
3. Verify results and handle errors
4. Report outcomes clearly"""

        super().__init__(goal=goal, tools=tools, model=model, system_prompt=system_prompt, **kwargs)
        self.actions = actions or []

    @property
    def agent_type(self) -> str:
        return "action"


class MetaAgent(BaseAgent):
    """Agent that coordinates other agents by invoking them as tools."""

    def __init__(
        self,
        goal: str,
        agents: dict[str, Agent] | None = None,
        tools: list[Tool | Callable] | None = None,
        model: str | None = None,
        **kwargs,
    ):
        self.sub_agents = agents or {}
        tools = list(tools or [])

        # Auto-register each sub-agent as an invocable tool
        agent_descriptions = []
        for name, agent in self.sub_agents.items():

            def make_tool(a: Agent, agent_name: str) -> Callable:
                def invoke_agent(task: str) -> str:
                    """Invoke a sub-agent with a specific task."""
                    ctx = ExecutionContext(goal=task, data={})
                    result = a.execute(ctx)
                    return result.output or f"{agent_name} completed with no output"

                invoke_agent.__name__ = f"invoke_{agent_name}"
                invoke_agent.__doc__ = (
                    f"Invoke the '{agent_name}' agent. "
                    f"Pass a specific task description as the 'task' parameter."
                )
                return invoke_agent

            tools.append(make_tool(agent, name))
            agent_type = agent.agent_type if hasattr(agent, "agent_type") else "unknown"
            agent_descriptions.append(f"- invoke_{name}: {agent_type} agent")

        agents_info = (
            "\n".join(agent_descriptions) if agent_descriptions else "No agents available."
        )
        system_prompt = f"""You are a meta agent (orchestrator) with the goal: {goal}

Your task is to coordinate and delegate work to other agents using your tools.

Available agent tools:
{agents_info}

Approach:
1. Break down the goal into sub-tasks
2. Use invoke_<agent_name>(task="...") to delegate work to the right agent
3. Synthesize results from all agents into a final output"""

        super().__init__(goal=goal, tools=tools, model=model, system_prompt=system_prompt, **kwargs)

    @property
    def agent_type(self) -> str:
        return "meta"
