"""Pipeline progress tracking for LCA analysis steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(Enum):
    """Status of a pipeline step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStep:
    """A single step in the LCA pipeline."""

    name: str
    description: str
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None


@dataclass
class StepIndicator:
    """Tracks progress of the LCA analysis pipeline.

    Provides step status for UI progress indicators.
    """

    steps: list[PipelineStep] = field(default_factory=list)

    def add_step(self, name: str, description: str) -> PipelineStep:
        """Add a step to the pipeline."""
        step = PipelineStep(name=name, description=description)
        self.steps.append(step)
        return step

    def start_step(self, name: str) -> PipelineStep | None:
        """Mark a step as running."""
        step = self._find_step(name)
        if step:
            step.status = StepStatus.RUNNING
        return step

    def complete_step(self, name: str, result: Any = None) -> PipelineStep | None:
        """Mark a step as completed."""
        step = self._find_step(name)
        if step:
            step.status = StepStatus.COMPLETED
            step.result = result
        return step

    def fail_step(self, name: str, error: str) -> PipelineStep | None:
        """Mark a step as failed."""
        step = self._find_step(name)
        if step:
            step.status = StepStatus.FAILED
            step.error = error
        return step

    def skip_step(self, name: str) -> PipelineStep | None:
        """Mark a step as skipped."""
        step = self._find_step(name)
        if step:
            step.status = StepStatus.SKIPPED
        return step

    @property
    def current_step(self) -> PipelineStep | None:
        """Get the currently running step."""
        for step in self.steps:
            if step.status == StepStatus.RUNNING:
                return step
        return None

    @property
    def is_complete(self) -> bool:
        """Check if all steps are completed or skipped."""
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    @property
    def has_failures(self) -> bool:
        """Check if any step has failed."""
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def to_dict(self) -> list[dict[str, Any]]:
        """Convert steps to list of dicts for serialization."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "status": s.status.value,
                "error": s.error,
            }
            for s in self.steps
        ]

    def _find_step(self, name: str) -> PipelineStep | None:
        """Find a step by name."""
        for step in self.steps:
            if step.name == name:
                return step
        return None


def create_lca_step_indicator() -> StepIndicator:
    """Create a StepIndicator pre-configured with LCA pipeline steps."""
    indicator = StepIndicator()
    indicator.add_step("parse_csv", "Parsing CSV data")
    indicator.add_step("io_table", "Building IO tables")
    indicator.add_step("hotspot", "Analyzing environmental hotspots")
    indicator.add_step("narrative", "Generating narrative report")
    return indicator
