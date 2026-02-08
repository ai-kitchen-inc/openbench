"""
World-class Workflow abstraction.

A Workflow is a named, stateful Chainable with automatic checkpointing.
The workflow structure is expressed directly in the chain parameter.

Example:
    >>> # Sequential workflow
    >>> workflow = Workflow(
    ...     name="analysis",
    ...     chain=research | analysis | report
    ... )
    >>>
    >>> # DAG workflow with parallel
    >>> workflow = Workflow(
    ...     name="complex-analysis",
    ...     chain=(research & data_gathering) | analysis | (pdf & pptx)
    ... )
    >>>
    >>> # Execute
    >>> result = workflow.run(input_data)
    >>>
    >>> # Resume from checkpoint
    >>> result = workflow.resume(workflow_id)
"""

from typing import Any

from openbench.core import (
    Chainable,
    LocalStateStore,
    RunnableConfig,
    StatefulChainable,
    StateStore,
    WorkflowState,
)


class Workflow(StatefulChainable):
    """
    Named, stateful workflow with automatic checkpointing.

    A Workflow is a thin wrapper around StatefulChainable that provides:
    - Named workflows for easy identification
    - Automatic checkpointing and resume capability
    - Convenience methods (run, status, history)
    - Clean API for common workflow patterns

    The workflow structure is expressed directly via the `chain` parameter,
    which accepts any Chainable (sequential, parallel, conditional, DAG, etc.).

    Attributes:
        name: Workflow name
        chain: Chainable defining the workflow structure
        state_store: StateStore for persistence
        auto_checkpoint: Whether to checkpoint automatically

    Example:
        >>> # Simple sequential workflow
        >>> workflow = Workflow(
        ...     name="sustainability-report",
        ...     chain=research | analysis | content
        ... )
        >>> result = workflow.run({"project": "Q1 2026"})
        >>>
        >>> # Complex DAG workflow
        >>> workflow = Workflow(
        ...     name="multi-source-analysis",
        ...     chain=(
        ...         (video1 | video2 | video3)      # Sequential videos
        ...         & dictionary                     # Parallel with dict
        ...         & table                          # Parallel with table
        ...     ) | (                                # Then parallel analysis
        ...         research_agent & analysis_agent
        ...     ) | (                                # Then parallel output
        ...         pdf_generator & pptx_generator
        ...     )
        ... )
        >>> result = workflow.run()
        >>>
        >>> # Resume from failure
        >>> workflow.resume(workflow_id="abc123")
    """

    def __init__(
        self,
        name: str,
        chain: Chainable,
        state_store: StateStore | None = None,
        checkpoints: bool = True,
        metadata: dict[str, Any] | None = None,
    ):
        """
        Create a new workflow.

        Args:
            name: Workflow name (used for logging, tracking, resume)
            chain: Chainable defining the workflow structure (DAG)
            state_store: StateStore for persistence (defaults to LocalStateStore)
            checkpoints: Enable automatic checkpointing (default: True)
            metadata: Optional metadata to attach to workflow

        Example:
            >>> workflow = Workflow(
            ...     name="my-workflow",
            ...     chain=step1 | step2 | step3,
            ...     checkpoints=True
            ... )
        """
        # Default to local file-based state store
        if state_store is None:
            state_store = LocalStateStore(base_path="./workflow_state")

        # Initialize StatefulChainable with the chain
        super().__init__(
            chainable=chain,
            state_store=state_store,
            workflow_name=name,
            auto_checkpoint=checkpoints,
        )

        self.name = name
        self.chain = chain
        self.metadata = metadata or {}

    def run(self, input: Any = None, **kwargs) -> Any:
        """
        Execute the workflow.

        Convenience method that wraps invoke() with a more intuitive name.

        Args:
            input: Input data for the workflow
            **kwargs: Additional execution parameters

        Returns:
            Workflow output

        Example:
            >>> result = workflow.run({"project": "Market Analysis"})
        """
        config = RunnableConfig(metadata=self.metadata)
        return self.invoke(input, config=config, **kwargs)

    def status(self, workflow_id: str) -> WorkflowState | None:
        """
        Get the current status of a workflow execution.

        Args:
            workflow_id: ID of the workflow execution

        Returns:
            WorkflowState if found, None otherwise

        Example:
            >>> state = workflow.status("abc123")
            >>> print(f"Status: {state.status.value}")
            >>> print(f"Steps completed: {len(state.steps)}")
        """
        return self.get_state(workflow_id)

    def history(self, workflow_id: str) -> WorkflowState | None:
        """
        Get the execution history of a workflow.

        Alias for status() - returns the full WorkflowState including step history.

        Args:
            workflow_id: ID of the workflow execution

        Returns:
            WorkflowState with full execution history

        Example:
            >>> history = workflow.history("abc123")
            >>> for step in history.steps:
            ...     print(f"{step.step_name}: {step.status}")
        """
        return self.status(workflow_id)

    def __repr__(self) -> str:
        """String representation of the workflow."""
        return f"Workflow(name='{self.name}')"

    def __str__(self) -> str:
        """Human-readable workflow description."""
        return f"Workflow: {self.name}"


# Convenience function for quick workflow creation
def workflow(name: str, chain: Chainable, **kwargs) -> Workflow:
    """
    Create a workflow (function-style convenience wrapper).

    Args:
        name: Workflow name
        chain: Chainable defining workflow structure
        **kwargs: Additional Workflow parameters

    Returns:
        Workflow instance

    Example:
        >>> # Function-style creation
        >>> wf = workflow("my-workflow", agent1 | agent2 | agent3)
        >>> result = wf.run()
    """
    return Workflow(name=name, chain=chain, **kwargs)
