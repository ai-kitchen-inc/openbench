"""
Intelligence Layer - Agent Orchestration Engine
"""

from typing import Any, Dict, List, Optional, Union


class IntelligenceLayer:
    """
    The Intelligence Layer orchestrates AI agents to perform complex tasks.

    Examples:
        >>> # Create a simple agent
        >>> agent = IntelligenceLayer.create_agent(
        ...     task="Analyze Q4 sales data",
        ...     tools=["semantic_search", "sql_query"]
        ... )
        >>>
        >>> # Execute agent
        >>> result = agent.execute(data_layer)
        >>>
        >>> # Create multi-agent workflow
        >>> workflow = IntelligenceLayer.workflow([
        ...     ResearchAgent(goal="Gather data"),
        ...     AnalysisAgent(goal="Analyze trends"),
        ...     ContentAgent(goal="Write summary")
        ... ])
    """

    def __init__(self, model: str = "gpt-4", temperature: float = 0.7):
        """
        Initialize the Intelligence Layer.

        Args:
            model: Default LLM model to use
            temperature: Model temperature (0-1)
        """
        self.model = model
        self.temperature = temperature
        print(f"🧠 IntelligenceLayer initialized with model={model}")

    @classmethod
    def create_agent(
        cls,
        task: str,
        agent_type: str = "research",
        tools: Optional[List[str]] = None,
        model: str = "gpt-4",
        **kwargs
    ) -> Any:
        """
        Create a single AI agent.

        Args:
            task: Task description for the agent
            agent_type: Type of agent (research, analysis, content, action, meta)
            tools: List of tools available to the agent
            model: LLM model to use
            **kwargs: Additional agent configuration

        Returns:
            Configured agent instance
        """
        print(f"\n🤖 Creating {agent_type} agent")
        print(f"   Task: {task}")
        print(f"   Model: {model}")
        print(f"   Tools: {tools or 'default'}")

        from openbench.intelligence.agents import _create_agent
        agent = _create_agent(task, agent_type, tools, model, **kwargs)

        print("   ✓ Agent created\n")
        return agent

    @classmethod
    def workflow(
        cls,
        agents: List[Any],
        parallel: bool = True,
        checkpoints: bool = True,
        **kwargs
    ) -> "Workflow":
        """
        Create a multi-agent workflow.

        Args:
            agents: List of agents to orchestrate
            parallel: Enable parallel execution where possible
            checkpoints: Enable workflow checkpoints
            **kwargs: Additional workflow configuration

        Returns:
            Configured Workflow instance
        """
        from openbench.workflows.workflow import Workflow

        print(f"\n🔄 Creating workflow with {len(agents)} agent(s)")
        print(f"   Parallel execution: {parallel}")
        print(f"   Checkpoints: {checkpoints}")

        workflow = Workflow(
            agents=agents,
            parallel=parallel,
            checkpoints=checkpoints,
            **kwargs
        )

        print("   ✓ Workflow created\n")
        return workflow


class Agent:
    """Base agent class."""

    def __init__(
        self,
        goal: str,
        agent_type: str,
        tools: Optional[List[str]] = None,
        model: str = "gpt-4"
    ):
        self.goal = goal
        self.agent_type = agent_type
        self.tools = tools or []
        self.model = model

    def execute(self, data_layer: Optional[Any] = None, **kwargs) -> Dict[str, Any]:
        """
        Execute the agent's task.

        Args:
            data_layer: DataLayer instance for data access
            **kwargs: Additional execution parameters

        Returns:
            Agent execution results
        """
        print(f"\n▶️ Executing {self.agent_type} agent")
        print(f"   Goal: {self.goal}")

        # Mock execution
        import time
        time.sleep(1)

        result = {
            "agent_type": self.agent_type,
            "goal": self.goal,
            "status": "completed",
            "output": f"Mock output for {self.agent_type} agent",
            "sources_consulted": 12,
            "confidence": 0.89
        }

        print(f"   ✓ Execution complete (confidence: {result['confidence']})\n")
        return result

    def __repr__(self):
        return f"<{self.agent_type.title()}Agent: {self.goal[:50]}>"
