"""Tests for framework-agnostic agent interface."""

from __future__ import annotations

import time
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
    ProgressEvent,
    QueryRewriter,
    SimpleAgent,
    StructuredOutputAgent,
    ToolExecutor,
    _sanitize_for_json,
    _tool_result_to_json,
)

# Mirrors the local cap in BaseAgent.execute (kept in sync by the retry tests).
_MAX_EMPTY_RETRIES = 2


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


class SlowMockTool(MockTool):
    """Mock tool with a configurable execution delay and timeout."""

    def __init__(self, *, delay_seconds: float, timeout_seconds: float):
        super().__init__("slow_mock_tool")
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds

    def execute(self, **params) -> Any:
        time.sleep(self.delay_seconds)
        return {"result": "slow", "params": params}


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

    def test_execute_uses_tool_timeout_seconds_when_omitted(self):
        """Tool-specific timeout should replace the default 30s timeout."""
        executor = ToolExecutor()
        executor.register("slow", SlowMockTool(delay_seconds=0.05, timeout_seconds=0.01))

        with self.assertRaises(TimeoutError) as ctx:
            executor.execute("slow")

        self.assertIn("exceeded 0.01s timeout", str(ctx.exception))

    def test_execute_explicit_timeout_overrides_tool_timeout_seconds(self):
        """Explicit timeout should win over the tool's timeout_seconds."""
        executor = ToolExecutor()
        executor.register("slow", SlowMockTool(delay_seconds=0.02, timeout_seconds=0.001))

        result = executor.execute("slow", timeout=0.2, query="ok")

        self.assertEqual(result["result"], "slow")
        self.assertEqual(result["params"]["query"], "ok")

    def test_execute_callable_still_uses_default_timeout(self):
        """Plain callables should keep the ordinary 30s fallback."""
        executor = ToolExecutor()
        executor.register("add", lambda a, b: a + b)

        self.assertEqual(executor.execute("add", a=2, b=3), 5)

    def test_execute_tool_param_named_name_via_arguments(self):
        """A tool parameter called `name` must not collide with execute()'s own.

        Regression: custom_function.run_function(name, kwargs_json) raised
        "ToolExecutor.execute() got multiple values for argument 'name'".
        """
        executor = ToolExecutor()
        executor.register("describe", lambda name: name.upper())

        self.assertEqual(executor.execute("describe", arguments={"name": "add"}), "ADD")

    def test_execute_tool_param_named_name_via_kwargs(self):
        """Legacy kwargs style also works: execute()'s `name` is positional-only."""
        executor = ToolExecutor()
        executor.register("describe", lambda name: name.upper())

        self.assertEqual(executor.execute("describe", **{"name": "add"}), "ADD")

    def test_execute_tool_param_named_timeout_via_arguments(self):
        """A tool parameter called `timeout` reaches the tool, not the executor."""
        executor = ToolExecutor()
        executor.register("cfg", lambda timeout: {"tool_saw_timeout": timeout})

        result = executor.execute("cfg", arguments={"timeout": 5})

        self.assertEqual(result, {"tool_saw_timeout": 5})

    def test_execute_parallel_tool_param_named_name(self):
        """execute_parallel must pass colliding-named args through cleanly."""
        executor = ToolExecutor()
        executor.register("describe", lambda name: name.upper())

        results = executor.execute_parallel(
            [{"id": "c1", "name": "describe", "arguments": {"name": "add"}}]
        )

        self.assertIsNone(results[0]["error"])
        self.assertEqual(results[0]["result"], "ADD")


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


class FailingAfterToolLLMProvider(LLMProvider):
    """Returns one tool call, then fails when the agent asks for final text."""

    @property
    def provider_name(self) -> str:
        return "mock-failing"

    def __init__(self):
        self.call_count = 0

    def generate(self, prompt: Any, model: str, **params) -> LLMResponse:
        self.call_count += 1
        if self.call_count > 1:
            raise RuntimeError("400 INVALID_ARGUMENT")
        response = LLMResponse(text="", model=model, tokens_used=10, cost=0.0)
        response.tool_calls = [{"name": "mock_tool", "arguments": {}}]
        return response


class EmptyResponseLLMProvider(LLMProvider):
    """Returns empty text with a configurable empty-response finish_reason.

    Used to test that the agent's empty-response retry is skipped for a
    deterministic MAX_TOKENS dropout but kept for a transient one.
    """

    def __init__(self, finish_reason: str):
        self.finish_reason = finish_reason
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock-empty"

    def generate(self, prompt: Any, model: str, **params) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            text="",
            model=model,
            tokens_used=10,
            cost=0.0,
            metadata={"empty_response_diagnostics": {"finish_reason": self.finish_reason}},
        )


class TestBaseAgentEmptyResponseRetry(unittest.TestCase):
    """Empty-response retry must be MAX_TOKENS-aware (no wasted retries)."""

    @patch("openbench.intelligence.base.get_provider_service")
    def test_max_tokens_empty_response_is_not_retried(self, mock_get_service):
        """A MAX_TOKENS dropout is deterministic — retrying just burns calls."""
        provider = EmptyResponseLLMProvider("FinishReason.MAX_TOKENS")
        mock_service = MagicMock()
        mock_service.resolve.return_value = provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(goal="Test goal")
        result = agent.execute(ExecutionContext(goal="hi"))

        self.assertEqual(provider.call_count, 1)  # one call, no retries
        self.assertEqual(result.output, "")

    @patch("openbench.intelligence.base.get_provider_service")
    def test_transient_empty_response_is_retried(self, mock_get_service):
        """A non-MAX_TOKENS empty turn (Confidence Dropout) still retries."""
        provider = EmptyResponseLLMProvider("FinishReason.STOP")
        mock_service = MagicMock()
        mock_service.resolve.return_value = provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(goal="Test goal")
        agent.execute(ExecutionContext(goal="hi"))

        # initial call + the retries
        self.assertEqual(provider.call_count, 1 + _MAX_EMPTY_RETRIES)


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

    @patch("openbench.intelligence.base.get_provider_service")
    def test_execute_rolls_back_tool_turn_when_followup_llm_call_fails(self, mock_get_service):
        """A 400 after a tool result must not leave function responses in memory."""
        mock_provider = FailingAfterToolLLMProvider()
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(goal="Test goal", tools=[MockTool()])
        result = agent.execute(ExecutionContext(goal="Use the tool"))

        self.assertEqual(result.status, "failed")
        roles = [message.role for message in agent.memory.messages]
        self.assertEqual(roles, [MessageRole.SYSTEM, MessageRole.USER])

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


class TestParallelToolExecution(unittest.TestCase):
    """Test parallel tool execution in ToolExecutor."""

    def test_execute_parallel_two_tools(self):
        """Test two independent tools run concurrently."""
        import time

        executor = ToolExecutor()

        def slow_add(x: int, y: int) -> int:
            time.sleep(0.1)
            return x + y

        def slow_multiply(x: int, y: int) -> int:
            time.sleep(0.1)
            return x * y

        executor.register("add", slow_add, description="Add numbers")
        executor.register("multiply", slow_multiply, description="Multiply numbers")

        calls = [
            {"id": "call_0", "name": "add", "arguments": {"x": 2, "y": 3}},
            {"id": "call_1", "name": "multiply", "arguments": {"x": 4, "y": 5}},
        ]

        start = time.monotonic()
        results = executor.execute_parallel(calls)
        elapsed = time.monotonic() - start

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["result"], 5)
        self.assertEqual(results[1]["result"], 20)
        self.assertIsNone(results[0]["error"])
        self.assertIsNone(results[1]["error"])
        # Parallel should be faster than sequential (0.2s)
        self.assertLess(elapsed, 0.19)

    def test_execute_parallel_preserves_order(self):
        """Test results are returned in input order."""
        import time

        executor = ToolExecutor()

        def fast(x: int) -> str:
            return f"fast-{x}"

        def slow(x: int) -> str:
            time.sleep(0.05)
            return f"slow-{x}"

        executor.register("fast", fast, description="Fast tool")
        executor.register("slow", slow, description="Slow tool")

        calls = [
            {"id": "call_0", "name": "slow", "arguments": {"x": 1}},
            {"id": "call_1", "name": "fast", "arguments": {"x": 2}},
        ]

        results = executor.execute_parallel(calls)
        # Even though fast finishes first, results should be in input order
        self.assertEqual(results[0]["result"], "slow-1")
        self.assertEqual(results[1]["result"], "fast-2")

    def test_execute_parallel_one_failure(self):
        """Test one tool failure doesn't block others."""
        executor = ToolExecutor()

        def good() -> str:
            return "success"

        def bad() -> str:
            raise ValueError("Tool error")

        executor.register("good", good, description="Good tool")
        executor.register("bad", bad, description="Bad tool")

        calls = [
            {"id": "call_0", "name": "good", "arguments": {}},
            {"id": "call_1", "name": "bad", "arguments": {}},
        ]

        results = executor.execute_parallel(calls)
        self.assertEqual(results[0]["result"], "success")
        self.assertIsNone(results[0]["error"])
        self.assertIsNone(results[1]["result"])
        self.assertIn("Tool error", results[1]["error"])

    def test_execute_parallel_single_call(self):
        """Test parallel with single call still works."""
        executor = ToolExecutor()
        executor.register("echo", lambda msg: msg, description="Echo")

        calls = [{"id": "call_0", "name": "echo", "arguments": {"msg": "hello"}}]
        results = executor.execute_parallel(calls)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["result"], "hello")


class TestBaseAgentPlanning(unittest.TestCase):
    """Test BaseAgent planning integration."""

    @patch("openbench.intelligence.base.get_provider_service")
    def test_planning_injects_steps_into_memory(self, mock_service):
        """Test planning adds plan steps to agent memory."""
        import json

        mock_llm = MagicMock()
        mock_service.return_value.resolve.return_value = mock_llm

        # Planning call returns plan JSON
        plan_response = LLMResponse(
            text=json.dumps(
                {
                    "steps": ["Search data", "Analyze results"],
                    "estimated_tools": ["search"],
                    "reasoning": "Two-phase approach",
                }
            ),
            model="test",
            tokens_used=50,
            cost=0.01,
        )
        # Execution call returns final answer
        answer_response = LLMResponse(
            text="Analysis complete", model="test", tokens_used=100, cost=0.01
        )
        mock_llm.generate.side_effect = [plan_response, answer_response]
        mock_llm.generate_stream.return_value = iter([answer_response])

        agent = BaseAgent(goal="Analyze data", enable_planning=True)
        context = ExecutionContext(goal="Analyze quarterly data", data={})
        agent.execute(context)

        # Verify planning was called (first LLM call)
        self.assertGreaterEqual(mock_llm.generate.call_count, 1)
        # Verify plan was injected into memory
        system_messages = [m for m in agent.memory.messages if m.role == MessageRole.SYSTEM]
        plan_messages = [m for m in system_messages if "Execute this plan" in m.content]
        self.assertEqual(len(plan_messages), 1)
        self.assertIn("1. Search data", plan_messages[0].content)

    @patch("openbench.intelligence.base.get_provider_service")
    def test_planning_disabled_by_default(self, mock_service):
        """Test planning is not triggered when disabled."""
        mock_llm = MagicMock()
        mock_service.return_value.resolve.return_value = mock_llm
        mock_llm.generate.return_value = LLMResponse(
            text="Done", model="test", tokens_used=50, cost=0.01
        )

        agent = BaseAgent(goal="Simple task")  # enable_planning defaults to False
        context = ExecutionContext(goal="Do something", data={})
        agent.execute(context)

        # Only one LLM call (no planning call)
        self.assertEqual(mock_llm.generate.call_count, 1)


class TestBaseAgentParallelTools(unittest.TestCase):
    """Test BaseAgent with parallel tool execution."""

    @patch("openbench.intelligence.base.get_provider_service")
    def test_parallel_flag_enables_concurrent_execution(self, mock_service):
        """Test parallel_tool_execution uses execute_parallel."""
        mock_llm = MagicMock()
        mock_service.return_value.resolve.return_value = mock_llm

        # First call returns two tool calls, second call returns answer
        tool_response = LLMResponse(text="", model="test", tokens_used=50, cost=0.01)
        tool_response.tool_calls = [
            {"id": "call_0", "name": "add", "arguments": {"x": 1, "y": 2}},
            {"id": "call_1", "name": "multiply", "arguments": {"x": 3, "y": 4}},
        ]
        answer_response = LLMResponse(
            text="Done: 3 and 12", model="test", tokens_used=50, cost=0.01
        )
        mock_llm.generate.side_effect = [tool_response, answer_response]

        agent = BaseAgent(
            goal="Calculate",
            tools=[],
            parallel_tool_execution=True,
        )
        agent.tools.register("add", lambda x, y: x + y, description="Add")
        agent.tools.register("multiply", lambda x, y: x * y, description="Multiply")

        context = ExecutionContext(goal="Calculate 1+2 and 3*4", data={})
        result = agent.execute(context)

        self.assertEqual(result.status, "completed")
        # Both tools should have been called
        self.assertIn("add", result.metadata.get("tools_used", []))
        self.assertIn("multiply", result.metadata.get("tools_used", []))


class TestProgressEvent(unittest.TestCase):
    """Test ProgressEvent dataclass."""

    def test_create_with_phase_only(self):
        """Test creating progress event with phase only."""
        event = ProgressEvent(phase="Thinking")
        self.assertEqual(event.phase, "Thinking")
        self.assertEqual(event.detail, "")

    def test_create_with_detail(self):
        """Test creating progress event with detail."""
        event = ProgressEvent(phase="Running search_web", detail="query=AI")
        self.assertEqual(event.phase, "Running search_web")
        self.assertEqual(event.detail, "query=AI")


class TestBaseAgentProgressEvents(unittest.TestCase):
    """Test BaseAgent on_progress callback."""

    @patch("openbench.intelligence.base.get_provider_service")
    def test_on_progress_emits_thinking(self, mock_get_service):
        """Test that on_progress emits 'Thinking' for simple execution."""
        mock_provider = MockLLMProvider(["Response"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(goal="Test")
        context = ExecutionContext(goal="Do something", data={})

        progress_events: list[ProgressEvent] = []
        result = agent.execute(context, on_progress=progress_events.append)

        self.assertEqual(result.status, "completed")
        phases = [e.phase for e in progress_events]
        self.assertIn("Thinking", phases)

    @patch("openbench.intelligence.base.get_provider_service")
    def test_on_progress_emits_tool_execution(self, mock_get_service):
        """Test that on_progress emits tool names during execution."""
        mock_llm = MagicMock()
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_llm
        mock_get_service.return_value = mock_service

        # First call returns tool call, second returns final answer
        tool_response = LLMResponse(text="", model="test", tokens_used=50, cost=0.01)
        tool_response.tool_calls = [
            {"id": "call_0", "name": "search_web", "arguments": {"q": "AI"}},
        ]
        answer_response = LLMResponse(text="Found results", model="test", tokens_used=50, cost=0.01)
        mock_llm.generate.side_effect = [tool_response, answer_response]

        agent = BaseAgent(goal="Research", tools=[])
        agent.tools.register("search_web", lambda q: "results", description="Search")

        context = ExecutionContext(goal="Search for AI", data={})
        progress_events: list[ProgressEvent] = []
        result = agent.execute(context, on_progress=progress_events.append)

        self.assertEqual(result.status, "completed")
        phases = [e.phase for e in progress_events]
        self.assertIn("Thinking", phases)
        self.assertIn("Running search_web", phases)
        self.assertIn("Analyzing results", phases)

    @patch("openbench.intelligence.base.get_provider_service")
    def test_on_progress_emits_planning(self, mock_get_service):
        """Test that on_progress emits 'Planning approach' when planning enabled."""
        import json

        mock_llm = MagicMock()
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_llm
        mock_get_service.return_value = mock_service

        plan_response = LLMResponse(
            text=json.dumps(
                {
                    "steps": ["Step 1"],
                    "estimated_tools": [],
                    "reasoning": "Simple plan",
                }
            ),
            model="test",
            tokens_used=50,
            cost=0.01,
        )
        answer_response = LLMResponse(text="Done", model="test", tokens_used=50, cost=0.01)
        mock_llm.generate.side_effect = [plan_response, answer_response]
        mock_llm.generate_stream.return_value = iter([answer_response])

        agent = BaseAgent(goal="Plan something", enable_planning=True)
        context = ExecutionContext(goal="Do a task", data={})

        progress_events: list[ProgressEvent] = []
        agent.execute(context, on_progress=progress_events.append)

        phases = [e.phase for e in progress_events]
        self.assertIn("Planning approach", phases)
        self.assertIn("Thinking", phases)

    @patch("openbench.intelligence.base.get_provider_service")
    def test_on_progress_emits_rag_retrieval(self, mock_get_service):
        """Test that on_progress emits 'Searching knowledge' for RAG."""
        mock_provider = MockLLMProvider(["Answer with context"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.items = [{"id": "doc1", "content": "Info", "metadata": {}}]
        mock_result.scores = [0.9]
        mock_store.search.return_value = mock_result

        agent = BaseAgent(goal="RAG test", store=mock_store)
        context = ExecutionContext(goal="What is X?", data={})

        progress_events: list[ProgressEvent] = []
        agent.execute(context, on_progress=progress_events.append)

        phases = [e.phase for e in progress_events]
        self.assertIn("Searching knowledge", phases)

    @patch("openbench.intelligence.base.get_provider_service")
    def test_on_progress_none_backward_compat(self, mock_get_service):
        """Test that on_progress=None works fine (backward compat)."""
        mock_provider = MockLLMProvider(["Response"])
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_provider
        mock_get_service.return_value = mock_service

        agent = BaseAgent(goal="Test")
        context = ExecutionContext(goal="Do something", data={})

        # Should not raise
        result = agent.execute(context, on_progress=None)
        self.assertEqual(result.status, "completed")

    @patch("openbench.intelligence.base.get_provider_service")
    def test_on_progress_multiple_tools(self, mock_get_service):
        """Test that multiple tool calls are listed in progress phase."""
        mock_llm = MagicMock()
        mock_service = MagicMock()
        mock_service.resolve.return_value = mock_llm
        mock_get_service.return_value = mock_service

        tool_response = LLMResponse(text="", model="test", tokens_used=50, cost=0.01)
        tool_response.tool_calls = [
            {"id": "call_0", "name": "search", "arguments": {}},
            {"id": "call_1", "name": "calculate", "arguments": {}},
        ]
        answer_response = LLMResponse(text="Done", model="test", tokens_used=50, cost=0.01)
        mock_llm.generate.side_effect = [tool_response, answer_response]

        agent = BaseAgent(goal="Multi-tool", tools=[])
        agent.tools.register("search", lambda: "found", description="Search")
        agent.tools.register("calculate", lambda: 42, description="Calc")

        context = ExecutionContext(goal="Search and calculate", data={})
        progress_events: list[ProgressEvent] = []
        agent.execute(context, on_progress=progress_events.append)

        phases = [e.phase for e in progress_events]
        # Should have a phase that mentions both tools
        tool_phase = [p for p in phases if p.startswith("Running")]
        self.assertEqual(len(tool_phase), 1)
        self.assertIn("search", tool_phase[0])
        self.assertIn("calculate", tool_phase[0])


class TestSanitizeForJson(unittest.TestCase):
    """Regression tests for _sanitize_for_json / _tool_result_to_json.

    These cover the Gemini 'Invalid JSON payload received. Unexpected
    token NaN' crash: tool results from pandas/numpy contain float('nan')
    for empty cells, and Python's json.dumps emits those as bareword
    NaN literals which Gemini rejects.
    """

    def test_nan_replaced_with_none(self):
        self.assertIsNone(_sanitize_for_json(float("nan")))

    def test_infinity_replaced_with_none(self):
        self.assertIsNone(_sanitize_for_json(float("inf")))
        self.assertIsNone(_sanitize_for_json(float("-inf")))

    def test_finite_float_preserved(self):
        self.assertEqual(_sanitize_for_json(3.14), 3.14)
        self.assertEqual(_sanitize_for_json(0.0), 0.0)
        self.assertEqual(_sanitize_for_json(-1.5), -1.5)

    def test_nested_dict_with_nan(self):
        data = {
            "category": float("nan"),
            "rule": "materials",
            "rows": [{"value": 1.0}, {"value": float("nan")}],
        }
        result = _sanitize_for_json(data)
        self.assertIsNone(result["category"])
        self.assertEqual(result["rule"], "materials")
        self.assertEqual(result["rows"][0]["value"], 1.0)
        self.assertIsNone(result["rows"][1]["value"])

    def test_list_with_mixed_values(self):
        result = _sanitize_for_json([1.0, float("nan"), "text", None, 2.5])
        self.assertEqual(result, [1.0, None, "text", None, 2.5])

    def test_tuple_becomes_list(self):
        # Tuples aren't JSON-native; they serialize as lists anyway,
        # so we flatten them to lists during sanitization.
        result = _sanitize_for_json((1.0, float("nan"), 3.0))
        self.assertEqual(result, [1.0, None, 3.0])

    def test_non_numeric_values_untouched(self):
        self.assertEqual(_sanitize_for_json("hello"), "hello")
        self.assertEqual(_sanitize_for_json(42), 42)
        self.assertTrue(_sanitize_for_json(True))
        self.assertIsNone(_sanitize_for_json(None))

    def test_tool_result_to_json_produces_strict_json(self):
        """The main regression: a tool result containing NaN must
        round-trip through strict json.loads (which rejects NaN)."""
        import json

        result = {
            "pareto_threshold": 0.8,
            "categories": [
                {
                    "category": float("nan"),  # empty cell from pandas
                    "rule": "materials",
                    "total": 1234.5,
                    "rows": [
                        {"process": "A", "amount": 100.0},
                        {"process": "B", "amount": float("nan")},
                    ],
                }
            ],
        }
        serialized = _tool_result_to_json(result)
        # Strict parser (no allow_nan=True equivalent on load)
        parsed = json.loads(serialized)
        self.assertIsNone(parsed["categories"][0]["category"])
        self.assertEqual(parsed["categories"][0]["rule"], "materials")
        self.assertIsNone(parsed["categories"][0]["rows"][1]["amount"])

    def test_tool_result_to_json_rejects_nan_literal(self):
        """Output must never contain the bareword 'NaN' literal."""
        serialized = _tool_result_to_json({"x": float("nan")})
        self.assertNotIn("NaN", serialized)
        self.assertIn("null", serialized)

    def test_tool_result_to_json_handles_non_serializable(self):
        """Non-JSON-native types still fall through default=str."""
        from pathlib import Path

        serialized = _tool_result_to_json({"path": Path("/tmp/x"), "v": float("nan")})
        parsed = __import__("json").loads(serialized)
        self.assertIsNone(parsed["v"])
        self.assertTrue(parsed["path"].endswith("x"))


if __name__ == "__main__":
    unittest.main()
