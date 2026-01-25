"""
State management for workflows.

Enables checkpointing, pause/resume, and replay capabilities.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import json
import pickle
from pathlib import Path

from openbench.core.chainable import Chainable, RunnableConfig


class WorkflowStatus(Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepRecord:
    """Record of a single workflow step execution."""
    step_name: str
    step_index: int
    input_data: Any
    output_data: Any
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    status: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['started_at'] = self.started_at.isoformat()
        data['completed_at'] = self.completed_at.isoformat()

        # Handle output_data serialization
        if self.output_data is not None:
            data['output_data'] = self._serialize_data(self.output_data)
        if self.input_data is not None:
            data['input_data'] = self._serialize_data(self.input_data)

        return data

    @staticmethod
    def _serialize_data(data: Any) -> Any:
        """Serialize data for JSON storage."""
        if hasattr(data, 'to_dict'):
            return data.to_dict()
        elif isinstance(data, list):
            return [StepRecord._serialize_data(item) for item in data]
        elif isinstance(data, dict):
            return {k: StepRecord._serialize_data(v) for k, v in data.items()}
        elif isinstance(data, (str, int, float, bool, type(None))):
            return data
        else:
            # For complex objects without to_dict, store type info
            return {"__type__": type(data).__name__, "__repr__": repr(data)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepRecord":
        """Create from dictionary."""
        data['started_at'] = datetime.fromisoformat(data['started_at'])
        data['completed_at'] = datetime.fromisoformat(data['completed_at'])
        return cls(**data)


@dataclass
class WorkflowState:
    """
    State container for workflow execution.

    Tracks execution history and enables checkpoint/resume.
    """
    workflow_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Execution history
    steps: List[StepRecord] = field(default_factory=list)
    current_step_index: int = 0

    # Data
    initial_input: Any = None
    final_output: Any = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def checkpoint(
        self,
        step_name: str,
        step_index: int,
        input_data: Any,
        output_data: Any,
        started_at: datetime,
        completed_at: datetime,
        status: str = "completed",
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record a checkpoint for a workflow step.

        Args:
            step_name: Name of the step
            step_index: Index of the step in the workflow
            input_data: Input to the step
            output_data: Output from the step
            started_at: When step started
            completed_at: When step completed
            status: Step status
            error: Error message if step failed
            metadata: Additional metadata
        """
        duration = (completed_at - started_at).total_seconds()

        record = StepRecord(
            step_name=step_name,
            step_index=step_index,
            input_data=input_data,
            output_data=output_data,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            status=status,
            error=error,
            metadata=metadata or {}
        )

        self.steps.append(record)
        self.current_step_index = step_index + 1
        self.updated_at = datetime.now()

        if status == "failed":
            self.status = WorkflowStatus.FAILED
            self.error = error
        elif step_index == self.metadata.get('total_steps', 0) - 1:
            # Last step completed
            self.status = WorkflowStatus.COMPLETED
            self.completed_at = datetime.now()
            self.final_output = output_data

    def get_last_checkpoint(self) -> Optional[StepRecord]:
        """Get the most recent checkpoint."""
        return self.steps[-1] if self.steps else None

    def get_step(self, step_index: int) -> Optional[StepRecord]:
        """Get checkpoint for a specific step."""
        for step in self.steps:
            if step.step_index == step_index:
                return step
        return None

    def can_resume(self) -> bool:
        """Check if workflow can be resumed."""
        return self.status in [WorkflowStatus.PAUSED, WorkflowStatus.FAILED]

    def get_resume_point(self) -> int:
        """Get the step index to resume from."""
        if not self.can_resume():
            return 0
        return self.current_step_index

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'workflow_id': self.workflow_id,
            'workflow_name': self.workflow_name,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'steps': [step.to_dict() for step in self.steps],
            'current_step_index': self.current_step_index,
            'metadata': self.metadata,
            'error': self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        """Create from dictionary."""
        data['status'] = WorkflowStatus(data['status'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        if data['completed_at']:
            data['completed_at'] = datetime.fromisoformat(data['completed_at'])
        data['steps'] = [StepRecord.from_dict(step) for step in data['steps']]
        # Don't restore initial_input and final_output from dict (too large)
        data.pop('initial_input', None)
        data.pop('final_output', None)
        return cls(**data)


class StateStore(ABC):
    """
    Abstract interface for workflow state persistence.

    Implementations could use: Redis, PostgreSQL, local files, etc.
    """

    @abstractmethod
    def save(self, state: WorkflowState) -> None:
        """
        Save workflow state.

        Args:
            state: WorkflowState to save
        """
        pass

    @abstractmethod
    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """
        Load workflow state.

        Args:
            workflow_id: ID of workflow to load

        Returns:
            WorkflowState if found, None otherwise
        """
        pass

    @abstractmethod
    def delete(self, workflow_id: str) -> bool:
        """
        Delete workflow state.

        Args:
            workflow_id: ID of workflow to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def list_workflows(
        self,
        status: Optional[WorkflowStatus] = None,
        limit: int = 100
    ) -> List[WorkflowState]:
        """
        List workflow states.

        Args:
            status: Filter by status (optional)
            limit: Maximum number to return

        Returns:
            List of WorkflowState objects
        """
        pass


class LocalStateStore(StateStore):
    """
    Local file-based state store.

    Stores workflow states as JSON files in a directory.
    """

    def __init__(self, base_path: str = "./workflow_state"):
        """
        Initialize local state store.

        Args:
            base_path: Directory to store state files
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_path(self, workflow_id: str) -> Path:
        """Get file path for workflow state."""
        return self.base_path / f"{workflow_id}.json"

    def save(self, state: WorkflowState) -> None:
        """Save workflow state to JSON file."""
        path = self._get_path(state.workflow_id)
        with open(path, 'w') as f:
            json.dump(state.to_dict(), f, indent=2)

    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load workflow state from JSON file."""
        path = self._get_path(workflow_id)
        if not path.exists():
            return None

        with open(path, 'r') as f:
            data = json.load(f)

        return WorkflowState.from_dict(data)

    def delete(self, workflow_id: str) -> bool:
        """Delete workflow state file."""
        path = self._get_path(workflow_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_workflows(
        self,
        status: Optional[WorkflowStatus] = None,
        limit: int = 100
    ) -> List[WorkflowState]:
        """List all workflow states."""
        workflows = []

        for path in self.base_path.glob("*.json"):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                state = WorkflowState.from_dict(data)

                if status is None or state.status == status:
                    workflows.append(state)

                if len(workflows) >= limit:
                    break
            except Exception:
                # Skip corrupted files
                continue

        return sorted(workflows, key=lambda s: s.updated_at, reverse=True)


class StatefulChainable(Chainable):
    """
    Chainable wrapper that adds state management to any Chainable.

    Automatically checkpoints execution and enables pause/resume.

    Example:
        >>> # Wrap a workflow with state management
        >>> workflow = Chain([loader, processor, analyzer])
        >>> stateful_workflow = StatefulChainable(
        ...     chainable=workflow,
        ...     state_store=LocalStateStore(),
        ...     workflow_name="data_analysis"
        ... )
        >>>
        >>> # Execute - auto-checkpoints after each step
        >>> result = stateful_workflow.invoke(input_data)
        >>>
        >>> # Resume from failure
        >>> result = stateful_workflow.resume(workflow_id="abc123")
    """

    def __init__(
        self,
        chainable: Chainable,
        state_store: StateStore,
        workflow_name: str,
        auto_checkpoint: bool = True
    ):
        """
        Initialize stateful chainable.

        Args:
            chainable: Chainable to wrap
            state_store: StateStore for persistence
            workflow_name: Name for this workflow
            auto_checkpoint: Automatically checkpoint after each step
        """
        self.chainable = chainable
        self.state_store = state_store
        self.workflow_name = workflow_name
        self.auto_checkpoint = auto_checkpoint

    def invoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        workflow_id: Optional[str] = None
    ) -> Any:
        """
        Execute with state management.

        Args:
            input: Input data
            config: Execution configuration
            workflow_id: Optional workflow ID (for resume)

        Returns:
            Output data
        """
        # Create or load state
        if workflow_id:
            state = self.state_store.load(workflow_id)
            if not state:
                raise ValueError(f"Workflow {workflow_id} not found")
        else:
            from uuid import uuid4
            workflow_id = str(uuid4())
            state = WorkflowState(
                workflow_id=workflow_id,
                workflow_name=self.workflow_name,
                initial_input=input
            )
            state.status = WorkflowStatus.RUNNING
            self.state_store.save(state)

        try:
            # Execute chainable
            started_at = datetime.now()
            output = self.chainable.invoke(input, config)
            completed_at = datetime.now()

            # Checkpoint success
            if self.auto_checkpoint:
                state.checkpoint(
                    step_name=self.workflow_name,
                    step_index=0,
                    input_data=input,
                    output_data=output,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="completed"
                )
                state.status = WorkflowStatus.COMPLETED
                state.final_output = output
                self.state_store.save(state)

            return output

        except Exception as e:
            # Checkpoint failure
            state.checkpoint(
                step_name=self.workflow_name,
                step_index=0,
                input_data=input,
                output_data=None,
                started_at=started_at,
                completed_at=datetime.now(),
                status="failed",
                error=str(e)
            )
            state.status = WorkflowStatus.FAILED
            self.state_store.save(state)
            raise

    def resume(self, workflow_id: str, config: Optional[RunnableConfig] = None) -> Any:
        """
        Resume a paused or failed workflow.

        Args:
            workflow_id: ID of workflow to resume
            config: Execution configuration

        Returns:
            Output data
        """
        state = self.state_store.load(workflow_id)
        if not state:
            raise ValueError(f"Workflow {workflow_id} not found")

        if not state.can_resume():
            raise ValueError(f"Workflow {workflow_id} cannot be resumed (status: {state.status})")

        # Get last successful output as input
        last_checkpoint = state.get_last_checkpoint()
        if last_checkpoint and last_checkpoint.status == "completed":
            input_data = last_checkpoint.output_data
        else:
            input_data = state.initial_input

        # Resume execution
        state.status = WorkflowStatus.RUNNING
        self.state_store.save(state)

        return self.invoke(input_data, config, workflow_id)

    def pause(self, workflow_id: str) -> None:
        """
        Pause a running workflow.

        Args:
            workflow_id: ID of workflow to pause
        """
        state = self.state_store.load(workflow_id)
        if state:
            state.status = WorkflowStatus.PAUSED
            self.state_store.save(state)

    def get_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """
        Get current state of a workflow.

        Args:
            workflow_id: ID of workflow

        Returns:
            WorkflowState if found
        """
        return self.state_store.load(workflow_id)
