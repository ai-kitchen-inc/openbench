"""Tests for pre-built agents and AgentFactory."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    LLMResponse,
)
from openbench.core.registry import AgentRegistry
from openbench.intelligence.agents import (
    ActionAgent,
    AnalysisAgent,
    ContentAgent,
    MetaAgent,
    ResearchAgent,
)
from openbench.intelligence.base import BaseAgent, SimpleAgent, StructuredOutputAgent
from openbench.intelligence.layer import AgentFactory

# ============================================================================
# Helpers
# ============================================================================


def _mock_llm_provider(response_text: str = "mock response") -> MagicMock:
    """Create a mock LLM provider that returns fixed text."""
    provider = MagicMock(spec=LLMProvider)
    provider.generate.return_value = LLMResponse(
        content=response_text,
        model="test-model",
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    return provider


def _mock_context(goal: str = "test goal", data: Any = None) -> ExecutionContext:
    return ExecutionContext(goal=goal, data=data or {})


# ============================================================================
# ResearchAgent
# ============================================================================


class TestResearchAgent(unittest.TestCase):
    """Test ResearchAgent specialized agent."""

    def test_agent_type(self):
        """Should return 'research'."""
        agent = ResearchAgent(goal="research task")
        self.assertEqual(agent.agent_type, "research")

    def test_default_sources(self):
        """Should default to ['all'] sources."""
        agent = ResearchAgent(goal="research")
        self.assertEqual(agent.sources, ["all"])

    def test_custom_sources(self):
        """Should accept custom sources."""
        agent = ResearchAgent(goal="research", sources=["web", "db"])
        self.assertEqual(agent.sources, ["web", "db"])

    def test_depth(self):
        """Should accept depth parameter."""
        agent = ResearchAgent(goal="research", depth="deep")
        self.assertEqual(agent.depth, "deep")

    def test_system_prompt_contains_goal(self):
        """System prompt should include the goal."""
        agent = ResearchAgent(goal="find climate data")
        self.assertIn("find climate data", agent._system_prompt)

    def test_system_prompt_contains_depth(self):
        """System prompt should include the depth."""
        agent = ResearchAgent(goal="research", depth="deep")
        self.assertIn("deep", agent._system_prompt)

    @patch.object(BaseAgent, "execute")
    def test_execute_enriches_metadata(self, mock_execute):
        """Execute should add sources_used and depth to metadata."""
        mock_execute.return_value = ExecutionResult(
            output="findings", status="success", metadata={}
        )
        agent = ResearchAgent(goal="test", sources=["web"], depth="standard")
        ctx = _mock_context()

        result = agent.execute(ctx)

        self.assertEqual(result.metadata["sources_used"], ["web"])
        self.assertEqual(result.metadata["depth"], "standard")

    @patch.object(BaseAgent, "execute")
    def test_execute_no_enrichment_on_empty_output(self, mock_execute):
        """Should not enrich metadata when output is empty."""
        mock_execute.return_value = ExecutionResult(output="", status="success", metadata={})
        agent = ResearchAgent(goal="test")
        ctx = _mock_context()

        result = agent.execute(ctx)

        self.assertNotIn("sources_used", result.metadata)


# ============================================================================
# AnalysisAgent
# ============================================================================


class TestAnalysisAgent(unittest.TestCase):
    """Test AnalysisAgent specialized agent."""

    def test_agent_type(self):
        """Should return 'analysis'."""
        agent = AnalysisAgent(goal="analyze data")
        self.assertEqual(agent.agent_type, "analysis")

    def test_default_methods(self):
        """Should default to statistical + trend_detection."""
        agent = AnalysisAgent(goal="analyze")
        self.assertEqual(agent.methods, ["statistical", "trend_detection"])

    def test_custom_methods(self):
        """Should accept custom methods."""
        agent = AnalysisAgent(goal="analyze", methods=["regression", "clustering"])
        self.assertEqual(agent.methods, ["regression", "clustering"])

    def test_system_prompt_contains_methods(self):
        """System prompt should include analysis methods."""
        agent = AnalysisAgent(goal="analyze", methods=["regression"])
        self.assertIn("regression", agent._system_prompt)

    @patch.object(BaseAgent, "execute")
    def test_execute_injects_methods_in_context(self, mock_execute):
        """Execute should inject analysis_methods into context data."""
        mock_execute.return_value = ExecutionResult(
            output="insights", status="success", metadata={}
        )
        agent = AnalysisAgent(goal="analyze", methods=["regression"])
        ctx = _mock_context()

        agent.execute(ctx)

        # Verify the context passed to super().execute() has methods
        call_args = mock_execute.call_args
        passed_ctx = call_args[0][0]
        self.assertEqual(passed_ctx.data["analysis_methods"], ["regression"])

    @patch.object(BaseAgent, "execute")
    def test_execute_enriches_metadata(self, mock_execute):
        """Execute should add methods to result metadata."""
        mock_execute.return_value = ExecutionResult(
            output="insights", status="success", metadata={}
        )
        agent = AnalysisAgent(goal="analyze")
        result = agent.execute(_mock_context())

        self.assertEqual(result.metadata["methods"], ["statistical", "trend_detection"])


# ============================================================================
# ContentAgent
# ============================================================================


class TestContentAgent(unittest.TestCase):
    """Test ContentAgent specialized agent."""

    def test_agent_type(self):
        """Should return 'content'."""
        agent = ContentAgent(goal="write report")
        self.assertEqual(agent.agent_type, "content")

    def test_default_style(self):
        """Should default to 'professional' style."""
        agent = ContentAgent(goal="write")
        self.assertEqual(agent.style, "professional")

    def test_custom_style(self):
        """Should accept custom style."""
        agent = ContentAgent(goal="write", style="casual")
        self.assertEqual(agent.style, "casual")

    def test_length_optional(self):
        """Length should be optional."""
        agent = ContentAgent(goal="write")
        self.assertIsNone(agent.length)

    def test_custom_length(self):
        """Should accept custom length."""
        agent = ContentAgent(goal="write", length="500 words")
        self.assertEqual(agent.length, "500 words")

    def test_system_prompt_contains_style(self):
        """System prompt should include writing style."""
        agent = ContentAgent(goal="write", style="academic")
        self.assertIn("academic", agent._system_prompt)

    @patch.object(BaseAgent, "execute")
    def test_execute_enriches_metadata(self, mock_execute):
        """Execute should add style to metadata."""
        mock_execute.return_value = ExecutionResult(output="content", status="success", metadata={})
        agent = ContentAgent(goal="write", style="formal", length="1000 words")
        result = agent.execute(_mock_context())

        self.assertEqual(result.metadata["style"], "formal")
        self.assertEqual(result.metadata["target_length"], "1000 words")

    @patch.object(BaseAgent, "execute")
    def test_execute_no_length_in_metadata_when_none(self, mock_execute):
        """Should not add target_length when length is None."""
        mock_execute.return_value = ExecutionResult(output="content", status="success", metadata={})
        agent = ContentAgent(goal="write")
        result = agent.execute(_mock_context())

        self.assertNotIn("target_length", result.metadata)


# ============================================================================
# ActionAgent
# ============================================================================


class TestActionAgent(unittest.TestCase):
    """Test ActionAgent specialized agent."""

    def test_agent_type(self):
        """Should return 'action'."""
        agent = ActionAgent(goal="deploy")
        self.assertEqual(agent.agent_type, "action")

    def test_default_actions(self):
        """Should default to empty actions list."""
        agent = ActionAgent(goal="deploy")
        self.assertEqual(agent.actions, [])

    def test_custom_actions(self):
        """Should accept custom action descriptions."""
        actions = [
            {"name": "deploy", "description": "Deploy to prod"},
            {"name": "rollback", "description": "Rollback deployment"},
        ]
        agent = ActionAgent(goal="manage", actions=actions)
        self.assertEqual(len(agent.actions), 2)

    def test_system_prompt_contains_actions(self):
        """System prompt should list available actions."""
        actions = [{"name": "deploy", "description": "Deploy app"}]
        agent = ActionAgent(goal="manage", actions=actions)
        self.assertIn("deploy", agent._system_prompt)


# ============================================================================
# MetaAgent
# ============================================================================


class TestMetaAgent(unittest.TestCase):
    """Test MetaAgent (orchestrator)."""

    def test_agent_type(self):
        """Should return 'meta'."""
        agent = MetaAgent(goal="coordinate")
        self.assertEqual(agent.agent_type, "meta")

    def test_empty_sub_agents(self):
        """Should work with no sub-agents."""
        agent = MetaAgent(goal="coordinate")
        self.assertEqual(agent.sub_agents, {})

    def test_sub_agents_registered_as_tools(self):
        """Sub-agents should be auto-registered as callable tools."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.agent_type = "research"

        agent = MetaAgent(goal="coordinate", agents={"researcher": mock_agent})

        self.assertEqual(agent.sub_agents, {"researcher": mock_agent})
        # Should have at least one tool registered (the invoke_researcher tool)
        self.assertIn("invoke_researcher", agent.tools._tools)

    def test_system_prompt_lists_agents(self):
        """System prompt should list available agent tools."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.agent_type = "analysis"

        agent = MetaAgent(goal="coordinate", agents={"analyzer": mock_agent})
        self.assertIn("invoke_analyzer", agent._system_prompt)
        self.assertIn("analysis", agent._system_prompt)

    def test_invoke_tool_calls_sub_agent(self):
        """The generated invoke tool should call the sub-agent's execute."""
        mock_agent = MagicMock(spec=Agent)
        mock_agent.agent_type = "research"
        mock_agent.execute.return_value = ExecutionResult(
            output="research results", status="success", metadata={}
        )

        agent = MetaAgent(goal="coordinate", agents={"researcher": mock_agent})

        # Find the invoke_researcher tool in ToolExecutor._tools
        invoke_tool = None
        for name, tool in agent.tools._tools.items():
            if name.startswith("invoke_"):
                invoke_tool = tool
                break

        self.assertIsNotNone(invoke_tool)
        result = invoke_tool("find latest papers")
        self.assertEqual(result, "research results")
        mock_agent.execute.assert_called_once()


# ============================================================================
# AgentFactory
# ============================================================================


class TestAgentFactory(unittest.TestCase):
    """Test AgentFactory creation and registry."""

    def test_list_types(self):
        """Should list all registered agent types."""
        types = AgentFactory.list_types()
        # Built-in types: base, simple, structured, research, analysis, content, action, meta
        expected = {
            "base",
            "simple",
            "structured",
            "research",
            "analysis",
            "content",
            "action",
            "meta",
        }
        self.assertTrue(expected.issubset(set(types)))

    def test_create_research(self):
        """Should create a ResearchAgent."""
        agent = AgentFactory.create(goal="test", agent_type="research")
        self.assertIsInstance(agent, ResearchAgent)

    def test_create_analysis(self):
        """Should create an AnalysisAgent."""
        agent = AgentFactory.create(goal="test", agent_type="analysis")
        self.assertIsInstance(agent, AnalysisAgent)

    def test_create_content(self):
        """Should create a ContentAgent."""
        agent = AgentFactory.create(goal="test", agent_type="content")
        self.assertIsInstance(agent, ContentAgent)

    def test_create_action(self):
        """Should create an ActionAgent."""
        agent = AgentFactory.create(goal="test", agent_type="action")
        self.assertIsInstance(agent, ActionAgent)

    def test_create_meta(self):
        """Should create a MetaAgent."""
        agent = AgentFactory.create(goal="test", agent_type="meta")
        self.assertIsInstance(agent, MetaAgent)

    def test_create_simple(self):
        """Should create a SimpleAgent."""
        agent = AgentFactory.create(goal="test", agent_type="simple")
        self.assertIsInstance(agent, SimpleAgent)

    def test_create_base(self):
        """Should create a BaseAgent."""
        agent = AgentFactory.create(goal="test", agent_type="base")
        self.assertIsInstance(agent, BaseAgent)

    def test_create_structured(self):
        """Should create a StructuredOutputAgent."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        agent = AgentFactory.create(goal="test", agent_type="structured", output_schema=schema)
        self.assertIsInstance(agent, StructuredOutputAgent)

    def test_convenience_research(self):
        """research() convenience method should work."""
        agent = AgentFactory.research(goal="test")
        self.assertIsInstance(agent, ResearchAgent)

    def test_convenience_analysis(self):
        """analysis() convenience method should work."""
        agent = AgentFactory.analysis(goal="test")
        self.assertIsInstance(agent, AnalysisAgent)

    def test_convenience_content(self):
        """content() convenience method should work."""
        agent = AgentFactory.content(goal="test")
        self.assertIsInstance(agent, ContentAgent)

    def test_convenience_simple(self):
        """simple() convenience method should work."""
        agent = AgentFactory.simple(goal="test")
        self.assertIsInstance(agent, SimpleAgent)

    def test_convenience_action(self):
        """action() convenience method should work."""
        agent = AgentFactory.action(goal="test")
        self.assertIsInstance(agent, ActionAgent)

    def test_convenience_meta(self):
        """meta() convenience method should work."""
        agent = AgentFactory.meta(goal="test")
        self.assertIsInstance(agent, MetaAgent)

    def test_create_with_model(self):
        """Should pass model parameter through."""
        agent = AgentFactory.create(goal="test", agent_type="research", model="gemini-2.5-flash")
        self.assertEqual(agent.model, "gemini-2.5-flash")

    def test_list_providers(self):
        """Should list providers for a type."""
        providers = AgentFactory.list_providers("research")
        self.assertIn("default", providers)

    def test_register_custom_agent(self):
        """Should register and create custom agent types."""

        class CustomAgent(BaseAgent):
            @property
            def agent_type(self) -> str:
                return "custom_test"

        AgentFactory.register("custom_test", "default", CustomAgent, "Test agent")

        agent = AgentFactory.create(goal="test", agent_type="custom_test")
        self.assertIsInstance(agent, CustomAgent)

        # Clean up
        try:
            if "custom_test" in AgentRegistry._registries:
                del AgentRegistry._registries["custom_test"]
        except Exception:
            pass

    def test_create_invalid_type_raises(self):
        """Should raise for unregistered agent type."""
        with self.assertRaises(ValueError):
            AgentFactory.create(goal="test", agent_type="nonexistent_agent_type_xyz")


if __name__ == "__main__":
    unittest.main()
