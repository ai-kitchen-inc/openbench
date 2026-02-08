"""
CrewAI framework adapter for OpenBench.

Allows using CrewAI crews in OpenBench workflows.
"""

from typing import Any

from openbench.core import FrameworkAdapter


class CrewAIAdapter(FrameworkAdapter):
    """
    Adapter for CrewAI crews.

    Wraps CrewAI Crew to work in OpenBench workflows.

    Example:
        ```python
        from crewai import Crew, Agent, Task
        from openbench.adapters.crewai import CrewAIAdapter
        from openbench import Workflow
        from openbench.data import PDFSource
        from openbench.output import PPTXGenerator

        # Your existing CrewAI setup
        researcher = Agent(
            role="Researcher",
            goal="Research topics thoroughly",
            backstory="Expert researcher"
        )
        writer = Agent(
            role="Writer",
            goal="Write engaging content",
            backstory="Professional writer"
        )

        research_task = Task(
            description="Research the topic",
            agent=researcher
        )
        writing_task = Task(
            description="Write a report",
            agent=writer
        )

        crew = Crew(
            agents=[researcher, writer],
            tasks=[research_task, writing_task]
        )

        # Wrap in OpenBench workflow
        workflow = Workflow(
            name="crewai-workflow",
            chain=(
                PDFSource("doc.pdf")
                | CrewAIAdapter(crew)
                | PPTXGenerator()
            )
        )

        result = workflow.run({})
        ```
    """

    @property
    def framework_name(self) -> str:
        return "crewai"

    def __init__(self, crew: Any):
        """
        Initialize the CrewAI adapter.

        Args:
            crew: CrewAI Crew instance
        """
        self.crew = crew

    def invoke(self, input: Any, config: Any | None = None) -> Any:
        """
        Execute the CrewAI crew.

        Args:
            input: Input data (will be passed as inputs to crew.kickoff())
            config: Optional configuration

        Returns:
            Result from crew.kickoff()
        """
        # CrewAI crews use kickoff method
        # Input should be a dict with keys matching task inputs
        inputs = input if isinstance(input, dict) else {"input": input}

        result = self.crew.kickoff(inputs=inputs)
        return result
