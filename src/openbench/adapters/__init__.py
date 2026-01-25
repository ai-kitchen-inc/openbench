"""
Framework adapters for OpenBench.

OpenBench is a universal control plane - bring your own agents from any framework!

Available Adapters:
- LangChainAdapter: Wrap any LangChain Runnable
- AG2Adapter: Wrap AG2 (AutoGen) agents
- CrewAIAdapter: Wrap CrewAI crews
- E2BAdapter: Run custom code in sandboxed environments
- GoogleADKAdapter: Wrap Google ADK agents

Example:
    ```python
    from openbench.adapters.langchain import LangChainAdapter
    from langchain.agents import AgentExecutor
    from openbench import Workflow
    from openbench.data import WebSource
    from openbench.output import PDFGenerator

    # Your existing LangChain agent
    agent_executor = AgentExecutor(agent=my_agent, tools=tools)

    # Wrap in OpenBench workflow
    workflow = Workflow(
        name="hybrid-workflow",
        chain=(
            WebSource("https://example.com")  # OpenBench data layer
            | LangChainAdapter(agent_executor)  # Your LangChain agent
            | PDFGenerator()  # OpenBench output layer
        )
    )

    result = workflow.run({})
    ```
"""

from openbench.adapters.langchain import LangChainAdapter
from openbench.adapters.ag2 import AG2Adapter
from openbench.adapters.crewai import CrewAIAdapter
from openbench.adapters.e2b import E2BAdapter
from openbench.adapters.google_adk import GoogleADKAdapter

__all__ = [
    "LangChainAdapter",
    "AG2Adapter",
    "CrewAIAdapter",
    "E2BAdapter",
    "GoogleADKAdapter",
]
