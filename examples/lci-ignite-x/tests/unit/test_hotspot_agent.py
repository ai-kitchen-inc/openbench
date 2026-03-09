"""Unit tests for HotspotAnalysisAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lci_ignite.intelligence.hotspot_agent import HotspotAnalysisAgent


class TestHotspotAgentInit:
    def test_agent_type(self):
        """Test agent_type property."""
        with patch("openbench.intelligence.base.BaseAgent.__init__", return_value=None):
            agent = HotspotAnalysisAgent.__new__(HotspotAnalysisAgent)
            assert agent.agent_type == "hotspot_analysis"

    def test_tools_registered(self):
        """Test that all hotspot tools are registered."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = HotspotAnalysisAgent()

            tool_names = list(agent.tools._tools.keys())
            assert "calculate_pareto" in tool_names
            assert "create_pareto_chart" in tool_names
            assert "create_hotspot_table" in tool_names
            assert "create_hotspot_callout" in tool_names

    def test_multi_hop_rag_enabled(self):
        """Test that multi_hop_rag is enabled."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = HotspotAnalysisAgent()
            assert agent.multi_hop_rag is True

    def test_retrieve_knowledge_auto_registered_with_store(self):
        """Test that retrieve_knowledge tool is auto-registered when store is provided."""
        mock_store = MagicMock()
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = HotspotAnalysisAgent(store=mock_store)

            tool_names = list(agent.tools._tools.keys())
            assert "retrieve_knowledge" in tool_names

    def test_no_retrieve_knowledge_without_store(self):
        """Test that retrieve_knowledge is NOT registered without store."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = HotspotAnalysisAgent()

            tool_names = list(agent.tools._tools.keys())
            assert "retrieve_knowledge" not in tool_names

    def test_max_iterations(self):
        """Test max_iterations is set to 8."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = HotspotAnalysisAgent()
            assert agent.max_iterations == 8

    def test_custom_retrieval_top_k(self):
        """Test custom retrieval_top_k."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = HotspotAnalysisAgent(retrieval_top_k=10)
            assert agent.retrieval_top_k == 10
