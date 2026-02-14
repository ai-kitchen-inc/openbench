"""
AG2 (AutoGen) framework adapter for OpenBench.

Allows using AG2 agents in OpenBench workflows.
"""

from __future__ import annotations

from typing import Any

from openbench.core import FrameworkAdapter


class AG2Adapter(FrameworkAdapter):
    """
    Adapter for AG2 (AutoGen) agents.

    Wraps AG2 AssistantAgent to work in OpenBench workflows.

    Example:
        ```python
        from autogen import AssistantAgent, UserProxyAgent
        from openbench.adapters.ag2 import AG2Adapter
        from openbench import Workflow
        from openbench.data import PDFSource
        from openbench.output import PDFGenerator

        # Your existing AG2 agent
        my_ag2_agent = AssistantAgent(
            name="analyst",
            llm_config={"model": "gpt-4"}
        )

        # Wrap in OpenBench workflow
        workflow = Workflow(
            name="ag2-analysis",
            chain=(
                PDFSource("report.pdf")
                | AG2Adapter(my_ag2_agent)
                | PDFGenerator(template="executive")
            )
        )

        result = workflow.run({})
        ```
    """

    @property
    def framework_name(self) -> str:
        return "ag2"

    def __init__(self, agent: Any, user_proxy: Any | None = None):
        """
        Initialize the AG2 adapter.

        Args:
            agent: AG2 AssistantAgent
            user_proxy: Optional UserProxyAgent (will create default if not provided)
        """
        self.agent = agent
        self.user_proxy = user_proxy

        # Create default user proxy if not provided
        if self.user_proxy is None:
            try:
                from autogen import UserProxyAgent

                self.user_proxy = UserProxyAgent(
                    "user", code_execution_config=False, human_input_mode="NEVER"
                )
            except ImportError:
                raise ImportError(
                    "AG2 (autogen) is not installed. Install it with: pip install pyautogen"
                ) from None

    def invoke(self, input: Any, config: Any | None = None) -> Any:
        """
        Execute the AG2 agent.

        Args:
            input: Input message (will be converted to string)
            config: Optional configuration

        Returns:
            Last message content from the agent
        """
        # AG2 uses chat-based interaction
        message = input if isinstance(input, str) else str(input)

        self.user_proxy.initiate_chat(self.agent, message=message)

        # Return last message from agent
        return self.user_proxy.last_message()["content"]
