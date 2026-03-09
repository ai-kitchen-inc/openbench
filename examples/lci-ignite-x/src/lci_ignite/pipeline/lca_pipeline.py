"""LCA analysis pipeline orchestration.

Composes IOTableAgent -> HotspotAnalysisAgent -> NarrativeHotspotAgent
into a Workflow with checkpointing support.
"""

from __future__ import annotations

from openbench.core.chainable import Chain
from openbench.workflows import Workflow


def build_lca_pipeline(
    io_agent,
    hotspot_agent,
    narrative_agent,
    checkpoints: bool = True,
) -> Workflow:
    """Build the LCA analysis pipeline as a Workflow.

    Pipeline: IOTableAgent -> HotspotAnalysisAgent -> NarrativeHotspotAgent

    Each agent receives the previous agent's ExecutionResult as input.
    The Workflow provides checkpointing for resume on failure.

    Args:
        io_agent: IOTableAgent instance.
        hotspot_agent: HotspotAnalysisAgent instance.
        narrative_agent: NarrativeHotspotAgent instance.
        checkpoints: Enable checkpointing. Defaults to True.

    Returns:
        Workflow wrapping the agent chain.
    """
    chain = Chain(steps=[io_agent, hotspot_agent, narrative_agent])
    return Workflow(
        name="lca-analysis",
        chain=chain,
        checkpoints=checkpoints,
        metadata={"pipeline": "lca", "version": "1.0"},
    )
