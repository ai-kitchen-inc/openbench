"""Pre-built agent types extending BaseAgent."""

from typing import Any, Callable, Dict, List, Optional, Union

from openbench.core.abstractions import Tool
from openbench.intelligence.base import BaseAgent


class ResearchAgent(BaseAgent):
    """Agent specialized in gathering and synthesizing information."""

    def __init__(
        self,
        goal: str,
        sources: Optional[List[str]] = None,
        depth: str = "standard",
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: str = "gpt-4o",
        **kwargs
    ):
        # Build research-specific system prompt
        system_prompt = f"""You are a research agent with the goal: {goal}

Your task is to gather and synthesize information from available sources.
Research depth: {depth}
Available sources: {', '.join(sources) if sources else 'all'}

Approach:
1. Identify key information needs
2. Search and gather relevant data
3. Synthesize findings into coherent insights
4. Cite sources when possible"""

        super().__init__(
            goal=goal,
            tools=tools,
            model=model,
            system_prompt=system_prompt,
            **kwargs
        )
        self.sources = sources or ["all"]
        self.depth = depth

    @property
    def agent_type(self) -> str:
        return "research"


class AnalysisAgent(BaseAgent):
    """Agent specialized in data analysis and insights."""

    def __init__(
        self,
        goal: str,
        methods: Optional[List[str]] = None,
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: str = "gpt-4o",
        **kwargs
    ):
        methods_list = methods or ["statistical", "trend_detection"]
        system_prompt = f"""You are an analysis agent with the goal: {goal}

Your task is to analyze data and extract meaningful insights.
Analysis methods: {', '.join(methods_list)}

Approach:
1. Understand the data structure and context
2. Apply appropriate analysis methods
3. Identify patterns, trends, and anomalies
4. Provide actionable insights with supporting evidence"""

        super().__init__(
            goal=goal,
            tools=tools,
            model=model,
            system_prompt=system_prompt,
            **kwargs
        )
        self.methods = methods_list

    @property
    def agent_type(self) -> str:
        return "analysis"


class ContentAgent(BaseAgent):
    """Agent specialized in content generation."""

    def __init__(
        self,
        goal: str,
        style: str = "professional",
        length: Optional[str] = None,
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: str = "gpt-4o",
        **kwargs
    ):
        length_instruction = f"Target length: {length}" if length else "Appropriate length for the content type"
        system_prompt = f"""You are a content generation agent with the goal: {goal}

Your task is to create high-quality content.
Writing style: {style}
{length_instruction}

Guidelines:
1. Understand the audience and purpose
2. Structure content clearly
3. Use engaging and appropriate language
4. Ensure accuracy and clarity"""

        super().__init__(
            goal=goal,
            tools=tools,
            model=model,
            system_prompt=system_prompt,
            **kwargs
        )
        self.style = style
        self.length = length

    @property
    def agent_type(self) -> str:
        return "content"


class ActionAgent(BaseAgent):
    """Agent specialized in executing actions and integrations."""

    def __init__(
        self,
        goal: str,
        actions: Optional[List[Dict]] = None,
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: str = "gpt-4o",
        **kwargs
    ):
        actions_desc = "\n".join([f"- {a.get('name', 'action')}: {a.get('description', '')}" for a in (actions or [])])
        system_prompt = f"""You are an action agent with the goal: {goal}

Your task is to execute actions and integrations.
{f'Available actions:{chr(10)}{actions_desc}' if actions_desc else 'Use available tools to complete tasks.'}

Approach:
1. Plan the sequence of actions needed
2. Execute each action carefully
3. Verify results and handle errors
4. Report outcomes clearly"""

        super().__init__(
            goal=goal,
            tools=tools,
            model=model,
            system_prompt=system_prompt,
            **kwargs
        )
        self.actions = actions or []

    @property
    def agent_type(self) -> str:
        return "action"


class MetaAgent(BaseAgent):
    """Agent that coordinates other agents."""

    def __init__(
        self,
        goal: str,
        available_agents: Optional[List[str]] = None,
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: str = "gpt-4o",
        **kwargs
    ):
        agents_list = available_agents or []
        system_prompt = f"""You are a meta agent (orchestrator) with the goal: {goal}

Your task is to coordinate and delegate work to other agents.
{f'Available agents: {", ".join(agents_list)}' if agents_list else 'Coordinate available resources.'}

Approach:
1. Break down the goal into sub-tasks
2. Assign tasks to appropriate agents
3. Monitor progress and handle dependencies
4. Synthesize results into final output"""

        super().__init__(
            goal=goal,
            tools=tools,
            model=model,
            system_prompt=system_prompt,
            **kwargs
        )
        self.available_agents = agents_list

    @property
    def agent_type(self) -> str:
        return "meta"
