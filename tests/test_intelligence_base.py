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


if __name__ == "__main__":
    unittest.main()
