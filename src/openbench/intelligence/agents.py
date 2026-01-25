"""Pre-built agent types."""

from typing import Any, Dict, List, Optional
from openbench.intelligence.layer import Agent


class ResearchAgent(Agent):
    """Agent specialized in gathering and synthesizing information."""

    def __init__(
        self,
        goal: str,
        sources: Optional[List[str]] = None,
        depth: str = "standard",
        **kwargs
    ):
        super().__init__(goal=goal, agent_type="research", **kwargs)
        self.sources = sources or ["all"]
        self.depth = depth


class AnalysisAgent(Agent):
    """Agent specialized in data analysis and insights."""

    def __init__(
        self,
        goal: str,
        methods: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(goal=goal, agent_type="analysis", **kwargs)
        self.methods = methods or ["statistical", "trend_detection"]


class ContentAgent(Agent):
    """Agent specialized in content generation."""

    def __init__(
        self,
        goal: str,
        style: str = "professional",
        length: Optional[str] = None,
        **kwargs
    ):
        super().__init__(goal=goal, agent_type="content", **kwargs)
        self.style = style
        self.length = length


class ActionAgent(Agent):
    """Agent specialized in executing actions and integrations."""

    def __init__(
        self,
        goal: str,
        actions: Optional[List[Dict]] = None,
        **kwargs
    ):
        super().__init__(goal=goal, agent_type="action", **kwargs)
        self.actions = actions or []


class MetaAgent(Agent):
    """Agent that coordinates other agents."""

    def __init__(
        self,
        goal: str,
        available_agents: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(goal=goal, agent_type="meta", **kwargs)
        self.available_agents = available_agents or []


def _create_agent(
    task: str,
    agent_type: str,
    tools: Optional[List[str]],
    model: str,
    **kwargs
) -> Agent:
    """Factory function to create agents."""

    agent_classes = {
        "research": ResearchAgent,
        "analysis": AnalysisAgent,
        "content": ContentAgent,
        "action": ActionAgent,
        "meta": MetaAgent,
    }

    agent_class = agent_classes.get(agent_type, Agent)
    return agent_class(goal=task, tools=tools, model=model, **kwargs)
