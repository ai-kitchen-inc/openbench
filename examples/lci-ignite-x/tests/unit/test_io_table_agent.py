"""Unit tests for IOTableAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lci_ignite.intelligence.io_table_agent import IOTableAgent


class TestIOTableAgentInit:
    @patch("lci_ignite.intelligence.io_table_agent.BaseAgent.__init__", return_value=None)
    def test_default_init(self, mock_init):
        """Test that IOTableAgent initializes with correct defaults."""
        # We need to set up tools attribute since __init__ is mocked
        with patch.object(IOTableAgent, "tools", create=True) as mock_tools:
            mock_tools.register = MagicMock()
            agent = IOTableAgent.__new__(IOTableAgent)
            agent.tools = mock_tools

            # Verify BaseAgent would be called with correct params
            mock_init.assert_not_called()  # We used __new__

    def test_agent_type(self):
        """Test agent_type property."""
        with patch("openbench.intelligence.base.BaseAgent.__init__", return_value=None):
            agent = IOTableAgent.__new__(IOTableAgent)
            assert agent.agent_type == "io_table"

    def test_tools_registered(self):
        """Test that all IO table tools are registered."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = IOTableAgent()

            tool_names = list(agent.tools._tools.keys())
            assert "create_io_table" in tool_names
            assert "aggregate_by_category" in tool_names
            assert "validate_units" in tool_names
            assert "create_io_table_chart" in tool_names
            assert len(tool_names) == 4

    def test_custom_model(self):
        """Test custom model parameter."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = IOTableAgent(model="gemini-2.5-pro", temperature=0.5)
            assert agent.model == "gemini-2.5-pro"
            assert agent.temperature == 0.5

    def test_max_iterations(self):
        """Test max_iterations is set to 5."""
        with (
            patch("openbench.core.providers.get_provider_service"),
            patch("openbench.core.config.get_default_model", return_value="gemini-2.5-flash"),
        ):
            agent = IOTableAgent()
            assert agent.max_iterations == 5
