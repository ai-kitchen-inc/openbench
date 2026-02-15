"""Tests for framework-agnostic agent interface."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.core.abstractions import (
    ExecutionContext,
    LLMProvider,
    LLMResponse,
    Tool,
)
from openbench.intelligence.base import (
    AgentConfig,
    AgentMemory,
    BaseAgent,
    Message,
    MessageRole,
    QueryRewriter,
    SimpleAgent,
    StructuredOutputAgent,
    ToolExecutor,
)


class TestMessageRole(unittest.TestCase):
    """Test MessageRole enum."""

    def test_all_roles_exist(self):
        """Test all expected roles exist."""
        self.assertEqual(MessageRole.SYSTEM.value, "system")
        self.assertEqual(MessageRole.USER.value, "user")
        self.assertEqual(MessageRole.ASSISTANT.value, "assistant")
        self.assertEqual(MessageRole.TOOL.value, "tool")


class TestMessage(unittest.TestCase):
    """Test Message dataclass."""

    def test_create_message(self):
        """Test creating a message."""
        msg = Message(role=MessageRole.USER, content="Hello")

        self.assertEqual(msg.role, MessageRole.USER)
        self.assertEqual(msg.content, "Hello")

    def test_to_dict(self):
        """Test converting message to dict."""
        msg = Message(role=MessageRole.ASSISTANT, content="Response")
        data = msg.to_dict()

        self.assertEqual(data["role"], "assistant")
        self.assertEqual(data["content"], "Response")

    def test_to_dict_with_tool_info(self):
        """Test message with tool information."""
        msg = Message(
            role=MessageRole.TOOL,
            content="result",
            name="search",
            tool_call_id="call_123",
        )
        data = msg.to_dict()

        self.assertEqual(data["name"], "search")
        self.assertEqual(data["tool_call_id"], "call_123")


class TestAgentMemory(unittest.TestCase):
    """Test AgentMemory."""

    def test_create_memory(self):
        """Test creating memory."""
        memory = AgentMemory()
        self.assertEqual(len(memory.messages), 0)

    def test_add_messages(self):
        """Test adding messages."""
        memory = AgentMemory()
        memory.add_system("You are a helpful assistant")
        memory.add_user("Hello")
        memory.add_assistant("Hi there!")

        self.assertEqual(len(memory.messages), 3)
        self.assertEqual(memory.messages[0].role, MessageRole.SYSTEM)
        self.assertEqual(memory.messages[1].role, MessageRole.USER)
        self.assertEqual(memory.messages[2].role, MessageRole.ASSISTANT)

    def test_add_tool_result(self):
        """Test adding tool result."""
        memory = AgentMemory()
        memory.add_tool_result("call_1", "search", '{"results": []}')

        self.assertEqual(len(memory.messages), 1)
        self.assertEqual(memory.messages[0].role, MessageRole.TOOL)
        self.assertEqual(memory.messages[0].name, "search")

    def test_get_messages(self):
        """Test getting messages in LLM format."""
        memory = AgentMemory()
        memory.add_system("System")
        memory.add_user("User")

        messages = memory.get_messages()

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")

    def test_max_messages_trim(self):
        """Test trimming when max messages exceeded."""
        memory = AgentMemory(max_messages=5)

        for i in range(10):
            memory.add_user(f"Message {i}")

        self.assertEqual(len(memory.messages), 5)

    def test_max_messages_keeps_system(self):
        """Test that system message is preserved when trimming."""
        memory = AgentMemory(max_messages=3)
        memory.add_system("System prompt")

        for i in range(5):
            memory.add_user(f"Message {i}")

        self.assertEqual(len(memory.messages), 3)
        self.assertEqual(memory.messages[0].role, MessageRole.SYSTEM)

    def test_clear(self):
        """Test clearing memory."""
        memory = AgentMemory()
        memory.add_system("System")
        memory.add_user("User")

        memory.clear()

        # Should keep system message
        self.assertEqual(len(memory.messages), 1)
        self.assertEqual(memory.messages[0].role, MessageRole.SYSTEM)

    def test_clear_no_system(self):
        """Test clearing memory without system message."""
        memory = AgentMemory()
        memory.add_user("User")

        memory.clear()

        self.assertEqual(len(memory.messages), 0)


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(self, name: str = "mock_tool"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A mock tool"

    def execute(self, **params) -> Any:
        return {"result": "mock", "params": params}

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }


class TestToolExecutor(unittest.TestCase):
    """Test ToolExecutor."""

    def test_register_tool_instance(self):
        """Test registering a Tool instance."""
        executor = ToolExecutor()
        tool = MockTool()

        executor.register("mock", tool)

        self.assertIn("mock", executor)
        self.assertEqual(len(executor), 1)

    def test_register_callable(self):
        """Test registering a callable."""
        executor = ToolExecutor()

        def my_func(x: int) -> int:
            """Double a number."""
            return x * 2

        executor.register("double", my_func, description="Double a number")

        self.assertIn("double", executor)

    def test_register_from_list(self):
        """Test registering multiple tools."""
        executor = ToolExecutor()
        tool1 = MockTool("tool1")
        tool2 = MockTool("tool2")

        executor.register_from_list([tool1, tool2])

        self.assertEqual(len(executor), 2)
        self.assertIn("tool1", executor)
        self.assertIn("tool2", executor)

    def test_get_schemas(self):
        """Test getting tool schemas."""
        executor = ToolExecutor()
        tool = MockTool()
        executor.register("mock", tool)

        schemas = executor.get_schemas()

        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["function"]["name"], "mock_tool")

    def test_execute_tool(self):
        """Test executing a tool."""
        executor = ToolExecutor()
        tool = MockTool()
        executor.register("mock", tool)

        result = executor.execute("mock", query="test")

        self.assertEqual(result["result"], "mock")
        self.assertEqual(result["params"]["query"], "test")

    def test_execute_callable(self):
        """Test executing a callable."""
        executor = ToolExecutor()
        executor.register("add", lambda a, b: a + b)

        result = executor.execute("add", a=2, b=3)

        self.assertEqual(result, 5)

    def test_execute_not_found(self):
        """Test executing nonexistent tool."""
        executor = ToolExecutor()

        with self.assertRaises(ValueError) as ctx:
            executor.execute("nonexistent")

        self.assertIn("not found", str(ctx.exception))


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["Mock response"]
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(self, prompt: Any, model: str, **params) -> LLMResponse:
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return LLMResponse(
            text=response,
            model=model,
            tokens_used=100,
            cost=0.001,
        )


class TestBaseAgent(unittest.TestCase):
    """Test BaseAgent."""

    def test_create_agent(self):
        """Test creating an agent."""
        agent = BaseAgent(goal="Test goal", model="gpt-4o")

        self.assertEqual(agent.goal, "Test goal")
        self.assertEqual(agent.model, "gpt-4o")
        self.assertEqual(agent.agent_type, "base")

    def test_agent_with_tools(self):
        """Test agent with tools."""
        tool = MockTool()
        agent = BaseAgent(goal="Test", tools=[tool])

        self.assertEqual(len(agent.tools), 1)

    def test_agent_memory_initialized(self):
        """Test agent memory is initialized with system prompt."""
        agent = BaseAgent(goal="Test goal")

        messages = agent.memory.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Test goal", messages[0]["content"])

    def test_custom_system_prompt(self):
        """Test custom system prompt."""
        agent = BaseAgent(goal="Test", system_prompt="Custom prompt")

        messages = agent.memory.get_messages()
        self.assertEqual(messages[0]["content"], "Custom prompt")

    def test_reset(self):
        """Test resetting agent."""
        agent = BaseAgent(goal="Test")
        agent.memory.add_user("Hello")
        agent.memory.add_assistant("Hi")

        agent.reset()

        messages = agent.memory.get_messages()
        self.assertEqual(len(messages), 1)  # Only system prompt

    @patch("openbench.intelligence.base.get_provider_service")
    def test_execute(self, mock_get_service):
        """Test agent execution."""
        mock_provider = MockLLMProvider(["Test response"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(goal="Test goal")
        context = ExecutionContext(goal="Analyze data", data={"key": "value"})

        result = agent.execute(context)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Test response")
        self.assertGreater(result.tokens_used, 0)

    def test_estimate_cost(self):
        """Test cost estimation."""
        agent = BaseAgent(goal="Test", model="gpt-4o")
        context = ExecutionContext(goal="Test")

        cost = agent.estimate_cost(context)

        # Should return some estimate (may be 0 if model not in config)
        self.assertIsInstance(cost, float)
        self.assertGreaterEqual(cost, 0)


class TestSimpleAgent(unittest.TestCase):
    """Test SimpleAgent."""

    def test_agent_type(self):
        """Test simple agent type."""
        agent = SimpleAgent(goal="Test")
        self.assertEqual(agent.agent_type, "simple")

    @patch("openbench.intelligence.base.get_provider_service")
    def test_execute_no_tools(self, mock_get_service):
        """Test simple agent execution without tools."""
        mock_provider = MockLLMProvider(["Simple response"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        agent = SimpleAgent(goal="Simple task")
        context = ExecutionContext(goal="Do something")

        result = agent.execute(context)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Simple response")


class TestStructuredOutputAgent(unittest.TestCase):
    """Test StructuredOutputAgent."""

    def test_agent_type(self):
        """Test structured agent type."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        agent = StructuredOutputAgent(goal="Extract", output_schema=schema)

        self.assertEqual(agent.agent_type, "structured")

    def test_system_prompt_includes_schema(self):
        """Test system prompt includes output schema."""
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        agent = StructuredOutputAgent(goal="Count items", output_schema=schema)

        messages = agent.memory.get_messages()
        self.assertIn("count", messages[0]["content"])

    @patch("openbench.intelligence.base.get_provider_service")
    def test_parse_json_response(self, mock_get_service):
        """Test parsing JSON from response."""
        mock_provider = MockLLMProvider(['{"name": "test", "value": 42}'])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        schema = {"type": "object"}
        agent = StructuredOutputAgent(goal="Extract", output_schema=schema)
        context = ExecutionContext(goal="Parse data")

        result = agent.execute(context)

        self.assertEqual(result.status, "completed")
        self.assertIsInstance(result.output, dict)
        self.assertEqual(result.output["name"], "test")

    @patch("openbench.intelligence.base.get_provider_service")
    def test_parse_json_in_markdown(self, mock_get_service):
        """Test parsing JSON from markdown code block."""
        response = '```json\n{"result": "success"}\n```'
        mock_provider = MockLLMProvider([response])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        schema = {"type": "object"}
        agent = StructuredOutputAgent(goal="Extract", output_schema=schema)
        context = ExecutionContext(goal="Parse")

        result = agent.execute(context)

        self.assertEqual(result.output["result"], "success")
        self.assertTrue(result.metadata.get("parsed"))


class TestAgentConfig(unittest.TestCase):
    """Test AgentConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AgentConfig()

        self.assertEqual(config.model, "gpt-4o")
        self.assertEqual(config.temperature, 0.7)
        self.assertEqual(config.max_iterations, 10)

    def test_custom_values(self):
        """Test custom configuration."""
        config = AgentConfig(
            model="claude-sonnet",
            temperature=0.3,
            max_tokens=1000,
        )

        self.assertEqual(config.model, "claude-sonnet")
        self.assertEqual(config.temperature, 0.3)
        self.assertEqual(config.max_tokens, 1000)


class TestQueryRewriter(unittest.TestCase):
    """Test QueryRewriter."""

    def test_rewrite_returns_valid_queries(self):
        """Test rewrite returns list of query strings."""
        mock_llm = MockLLMProvider(['["query about X", "details on Y"]'])
        rewriter = QueryRewriter(mock_llm, model="test-model")

        result = rewriter.rewrite("How does X relate to Y?")

        self.assertEqual(result, ["query about X", "details on Y"])

    def test_rewrite_caps_at_three(self):
        """Test rewrite caps results at 3 queries."""
        mock_llm = MockLLMProvider(['["q1", "q2", "q3", "q4", "q5"]'])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("big question")

        self.assertEqual(len(result), 3)

    def test_rewrite_handles_markdown_code_block(self):
        """Test rewrite strips markdown code block wrapper."""
        mock_llm = MockLLMProvider(['```json\n["optimized query"]\n```'])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("original query")

        self.assertEqual(result, ["optimized query"])

    def test_rewrite_fallback_on_invalid_json(self):
        """Test fallback to original query on invalid JSON."""
        mock_llm = MockLLMProvider(["not valid json"])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("original query")

        self.assertEqual(result, ["original query"])

    def test_rewrite_fallback_on_empty_list(self):
        """Test fallback to original query on empty list response."""
        mock_llm = MockLLMProvider(["[]"])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("original query")

        self.assertEqual(result, ["original query"])

    def test_rewrite_fallback_on_non_string_list(self):
        """Test fallback when response is list of non-strings."""
        mock_llm = MockLLMProvider(["[1, 2, 3]"])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("original query")

        self.assertEqual(result, ["original query"])

    def test_rewrite_with_context(self):
        """Test that context is included in prompt."""
        mock_llm = MockLLMProvider(['["contextualized query"]'])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("query", context="about medicine")

        self.assertEqual(result, ["contextualized query"])
        # Verify the LLM was called
        self.assertEqual(mock_llm.call_count, 1)

    def test_rewrite_fallback_on_exception(self):
        """Test fallback when LLM provider raises exception."""
        mock_llm = MagicMock(spec=["generate", "provider_name"])
        mock_llm.generate.side_effect = RuntimeError("API error")
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("my query")

        self.assertEqual(result, ["my query"])

    def test_rewrite_single_query(self):
        """Test rewrite with single valid query."""
        mock_llm = MockLLMProvider(['["single optimized query"]'])
        rewriter = QueryRewriter(mock_llm)

        result = rewriter.rewrite("test")

        self.assertEqual(result, ["single optimized query"])


class TestBaseAgentQueryRewriter(unittest.TestCase):
    """Test BaseAgent with query rewriter integration."""

    def setUp(self):
        """Set up mock store and provider."""
        self.mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.items = [
            {"id": "doc1", "content": "Content about X", "metadata": {}},
            {"id": "doc2", "content": "Content about Y", "metadata": {}},
        ]
        mock_result.scores = [0.9, 0.8]
        self.mock_store.search.return_value = mock_result

    @patch("openbench.intelligence.base.get_provider_service")
    def test_query_rewriter_enabled(self, mock_get_service):
        """Test query rewriter is used when enabled."""
        mock_provider = MockLLMProvider(
            ['["rewritten query 1", "rewritten query 2"]', "Final answer"]
        )
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(
            goal="Test",
            store=self.mock_store,
            query_rewriter=True,
        )

        results = agent._retrieve_context("original question")

        # Store.search should be called once per rewritten query
        self.assertEqual(self.mock_store.search.call_count, 2)
        self.assertGreater(len(results), 0)

    def test_query_rewriter_disabled_by_default(self):
        """Test query rewriter is disabled by default."""
        agent = BaseAgent(goal="Test", store=self.mock_store)

        self.assertIsNone(agent._get_query_rewriter())

    @patch("openbench.intelligence.base.get_provider_service")
    def test_retrieve_context_deduplicates(self, mock_get_service):
        """Test that duplicate results from multiple queries are deduplicated."""
        mock_provider = MockLLMProvider(['["q1", "q2"]', "answer"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        # Both queries return same doc1
        mock_result = MagicMock()
        mock_result.items = [{"id": "doc1", "content": "Same content", "metadata": {}}]
        mock_result.scores = [0.95]
        self.mock_store.search.return_value = mock_result

        agent = BaseAgent(
            goal="Test",
            store=self.mock_store,
            query_rewriter=True,
        )

        results = agent._retrieve_context("question")

        # Should only have 1 unique result despite 2 queries
        self.assertEqual(len(results), 1)


class TestBaseAgentMultiHopRAG(unittest.TestCase):
    """Test BaseAgent multi-hop RAG functionality."""

    def test_multi_hop_registers_tool(self):
        """Test that multi_hop_rag registers retrieve_knowledge tool."""
        mock_store = MagicMock()
        agent = BaseAgent(
            goal="Research task",
            store=mock_store,
            multi_hop_rag=True,
        )

        self.assertIn("retrieve_knowledge", agent.tools)

    def test_multi_hop_without_store_no_tool(self):
        """Test that multi_hop_rag without store doesn't register tool."""
        agent = BaseAgent(
            goal="Research task",
            multi_hop_rag=True,
        )

        self.assertNotIn("retrieve_knowledge", agent.tools)

    @patch("openbench.intelligence.base.get_provider_service")
    def test_multi_hop_skips_auto_retrieval(self, mock_get_service):
        """Test that multi_hop_rag skips auto-retrieval in execute()."""
        mock_provider = MockLLMProvider(["Answer without auto-retrieval"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        mock_store = MagicMock()
        agent = BaseAgent(
            goal="Research",
            store=mock_store,
            multi_hop_rag=True,
        )

        context = ExecutionContext(goal="Find something")
        agent.execute(context)

        # store.search should NOT be called during execute (no auto-retrieval)
        mock_store.search.assert_not_called()

    def test_rag_tool_retrieve_returns_formatted(self):
        """Test _rag_tool_retrieve returns formatted results."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.items = [
            {"id": "doc1", "content": "First document", "metadata": {}},
            {"id": "doc2", "content": "Second document", "metadata": {}},
        ]
        mock_result.scores = [0.9, 0.8]
        mock_store.search.return_value = mock_result

        agent = BaseAgent(
            goal="Research",
            store=mock_store,
            multi_hop_rag=True,
        )

        result = agent._rag_tool_retrieve("test query")

        self.assertIn("[Source 1]", result)
        self.assertIn("[Source 2]", result)
        self.assertIn("First document", result)
        self.assertIn("Second document", result)
        self.assertIn("0.90", result)

    def test_rag_tool_retrieve_no_results(self):
        """Test _rag_tool_retrieve with no results."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.items = []
        mock_result.scores = []
        mock_store.search.return_value = mock_result

        agent = BaseAgent(
            goal="Research",
            store=mock_store,
            multi_hop_rag=True,
        )

        result = agent._rag_tool_retrieve("no results query")

        self.assertEqual(result, "No relevant documents found for this query.")

    def test_rag_tool_retrieve_no_store(self):
        """Test _rag_tool_retrieve without store."""
        agent = BaseAgent(goal="Research")

        result = agent._rag_tool_retrieve("query")

        self.assertEqual(result, "No knowledge base configured.")


if __name__ == "__main__":
    unittest.main()
