"""
LangChain framework adapter for OpenBench.

Allows using any LangChain Runnable (agents, chains, LCEL) in OpenBench workflows.
"""

from __future__ import annotations

from typing import Any

from openbench.core import FrameworkAdapter


class LangChainAdapter(FrameworkAdapter):
    """
    Adapter for LangChain agents and chains.

    Wraps any LangChain Runnable to work in OpenBench workflows.

    Example:
        ```python
        from langchain.agents import create_react_agent, AgentExecutor
        from langchain_openai import ChatOpenAI
        from openbench.adapters.langchain import LangChainAdapter
        from openbench import Workflow
        from openbench.data import WebSource
        from openbench.output import PDFGenerator

        # Your existing LangChain agent
        llm = ChatOpenAI(model="gpt-4")
        agent = create_react_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools)

        # Wrap in OpenBench workflow
        workflow = Workflow(
            name="langchain-analysis",
            chain=(
                WebSource("https://example.com")
                | LangChainAdapter(agent_executor)
                | PDFGenerator()
            )
        )

        result = workflow.run({})
        ```
    """

    @property
    def framework_name(self) -> str:
        return "langchain"

    def __init__(self, runnable: Any):
        """
        Initialize the LangChain adapter.

        Args:
            runnable: Any LangChain Runnable (Agent, Chain, LCEL, etc.)
        """
        self.runnable = runnable

    def invoke(self, input: Any, config: Any | None = None) -> Any:
        """
        Execute the LangChain runnable.

        Args:
            input: Input data (LangChain Runnables accept various formats)
            config: LangChain RunnableConfig (optional)

        Returns:
            Output from the LangChain runnable
        """
        return self.runnable.invoke(input, config=config)

    async def ainvoke(self, input: Any, config: Any | None = None) -> Any:
        """
        Async execution of the LangChain runnable.

        Args:
            input: Input data
            config: LangChain RunnableConfig (optional)

        Returns:
            Output from the LangChain runnable
        """
        return await self.runnable.ainvoke(input, config=config)
