"""Unit tests for NarrativeHotspotAgent."""

from __future__ import annotations

from unittest.mock import patch

from lci_ignite.intelligence.narrative_agent import NarrativeHotspotAgent


class TestNarrativeAgentInit:
    def test_agent_type(self):
        """Test agent_type property."""
        with patch("openbench.intelligence.base.BaseAgent.__init__", return_value=None):
            agent = NarrativeHotspotAgent.__new__(NarrativeHotspotAgent)
            assert agent.agent_type == "narrative_hotspot"

    def test_tools_registered(self):
        """Test that all narrative tools are registered."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = NarrativeHotspotAgent()

            tool_names = list(agent.tools._tools.keys())
            assert "create_narrative_markdown" in tool_names
            assert "create_narrative_callout" in tool_names
            assert "export_to_docx" in tool_names

    def test_multi_hop_rag_enabled(self):
        """Test that multi_hop_rag is enabled."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = NarrativeHotspotAgent()
            assert agent.multi_hop_rag is True

    def test_higher_temperature(self):
        """Test that narrative agent uses higher temperature for creative writing."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = NarrativeHotspotAgent()
            assert agent.temperature == 0.7

    def test_max_iterations(self):
        """Test max_iterations is set to 6."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = NarrativeHotspotAgent()
            assert agent.max_iterations == 6
