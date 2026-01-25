"""
Google ADK framework adapter for OpenBench.

Allows using Google Agent Development Kit agents in OpenBench workflows.
"""

from typing import Any, Optional
from openbench.core import FrameworkAdapter


class GoogleADKAdapter(FrameworkAdapter):
    """
    Adapter for Google Agent Development Kit.

    Wraps Google ADK agents to work in OpenBench workflows.

    Example:
        ```python
        from openbench.adapters.google_adk import GoogleADKAdapter
        from openbench import Workflow
        from openbench.data import YouTubeSource
        from openbench.output import PPTXGenerator

        # Your existing Google ADK agent
        # (API is hypothetical - adjust based on actual Google ADK)
        from google.adk import Agent

        my_google_agent = Agent(
            name="analyst",
            model="gemini-pro"
        )

        # Wrap in OpenBench workflow
        workflow = Workflow(
            name="google-workflow",
            chain=(
                YouTubeSource("video_id")
                | GoogleADKAdapter(my_google_agent)
                | PPTXGenerator()
            )
        )

        result = workflow.run({})
        ```
    """

    @property
    def framework_name(self) -> str:
        return "google_adk"

    def __init__(self, agent: Any):
        """
        Initialize the Google ADK adapter.

        Args:
            agent: Google ADK Agent instance
        """
        self.agent = agent

    def invoke(self, input: Any, config: Optional[Any] = None) -> Any:
        """
        Execute the Google ADK agent.

        Args:
            input: Input data
            config: Optional configuration

        Returns:
            Output from the agent
        """
        # Google ADK API (adjust based on actual implementation)
        # Assuming the agent has a run() method
        if hasattr(self.agent, 'run'):
            response = self.agent.run(input)
            # Assuming response has an output attribute
            return response.output if hasattr(response, 'output') else response
        elif hasattr(self.agent, 'invoke'):
            return self.agent.invoke(input)
        else:
            raise NotImplementedError(
                "Google ADK agent must have either 'run()' or 'invoke()' method"
            )
