"""Unit tests for LCA pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

from lci_ignite.pipeline.lca_pipeline import build_lca_pipeline


class TestBuildLCAPipeline:
    def test_creates_workflow(self):
        io_agent = MagicMock()
        hotspot_agent = MagicMock()
        narrative_agent = MagicMock()

        workflow = build_lca_pipeline(io_agent, hotspot_agent, narrative_agent)

        assert workflow.name == "lca-analysis"

    def test_workflow_has_3_steps(self):
        io_agent = MagicMock()
        hotspot_agent = MagicMock()
        narrative_agent = MagicMock()

        workflow = build_lca_pipeline(io_agent, hotspot_agent, narrative_agent)

        # The workflow wraps a Chain with 3 steps
        assert len(workflow.chain.steps) == 3

    def test_checkpoints_enabled_by_default(self):
        io_agent = MagicMock()
        hotspot_agent = MagicMock()
        narrative_agent = MagicMock()

        workflow = build_lca_pipeline(io_agent, hotspot_agent, narrative_agent)
        assert workflow.auto_checkpoint is True

    def test_checkpoints_disabled(self):
        io_agent = MagicMock()
        hotspot_agent = MagicMock()
        narrative_agent = MagicMock()

        workflow = build_lca_pipeline(io_agent, hotspot_agent, narrative_agent, checkpoints=False)
        assert workflow.auto_checkpoint is False

    def test_workflow_metadata(self):
        io_agent = MagicMock()
        hotspot_agent = MagicMock()
        narrative_agent = MagicMock()

        workflow = build_lca_pipeline(io_agent, hotspot_agent, narrative_agent)
        assert workflow.metadata["pipeline"] == "lca"
        assert workflow.metadata["version"] == "1.0"
