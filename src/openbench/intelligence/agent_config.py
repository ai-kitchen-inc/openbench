"""Agent configuration and progress-event primitives.

Extracted from ``base.py`` so the small, dependency-light value types can be
imported without pulling in the full ``BaseAgent`` machinery. ``base`` re-exports
``AgentConfig``, ``ProgressEvent``, and ``_emit_progress`` for backward
compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openbench.core.config import get_default_model

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    model: str = field(default_factory=get_default_model)
    temperature: float = 0.7
    max_tokens: int | None = None
    max_iterations: int = 10
    system_prompt: str | None = None
    stop_sequences: list[str] = field(default_factory=list)


@dataclass
class ProgressEvent:
    """Progress update from agent execution.

    Emitted via ``on_progress`` callback during BaseAgent.execute() to report
    sub-phases (planning, tool use, analysis) for real-time UI indicators.
    """

    phase: str
    detail: str = ""


def _emit_progress(
    on_progress: Callable[[ProgressEvent], None] | None,
    phase: str,
    detail: str = "",
) -> None:
    """Safely emit a progress event if callback is provided."""
    if on_progress:
        on_progress(ProgressEvent(phase=phase, detail=detail))
