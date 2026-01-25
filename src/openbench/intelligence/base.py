"""
Framework-Agnostic Agent Interface for OpenBench.

Provides:
- BaseAgent: Framework-agnostic agent implementation
- ToolExecutor: Unified tool execution interface
- AgentMemory: Conversation and context memory
- AgentRunner: Execution engine for agents

This decouples agents from specific frameworks (Mastra, LangChain, etc.)
while maintaining compatibility with any LLM provider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
import json
import logging

from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    Tool,
)
from openbench.core.config import get_config, ModelInfo
from openbench.core.providers import ProviderType, get_provider_service

logger = logging.getLogger(__name__)


class MessageRole(Enum):
    """Role in conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """A message in agent conversation."""

    role: MessageRole
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to LLM-compatible format."""
        result = {"role": self.role.value, "content": self.content}
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        return result


@dataclass
class AgentMemory:
    """Agent conversation memory."""

    messages: List[Message] = field(default_factory=list)
    max_messages: int = 100
    max_tokens: Optional[int] = None

    def add(self, role: MessageRole, content: str, **kwargs) -> None:
        """Add message to memory."""
        self.messages.append(Message(role=role, content=content, **kwargs))

        # Trim if exceeds max
        if len(self.messages) > self.max_messages:
            # Keep system message if present
            if self.messages and self.messages[0].role == MessageRole.SYSTEM:
                self.messages = [self.messages[0]] + self.messages[-(self.max_messages - 1) :]
            else:
                self.messages = self.messages[-self.max_messages :]

    def add_system(self, content: str) -> None:
        """Add system message."""
        self.add(MessageRole.SYSTEM, content)

    def add_user(self, content: str) -> None:
        """Add user message."""
        self.add(MessageRole.USER, content)

    def add_assistant(self, content: str, tool_calls: Optional[List[Dict]] = None) -> None:
        """Add assistant message."""
        self.add(MessageRole.ASSISTANT, content, tool_calls=tool_calls)

    def add_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        """Add tool result message."""
        self.add(MessageRole.TOOL, result, name=name, tool_call_id=tool_call_id)

    def get_messages(self) -> List[Dict[str, Any]]:
        """Get messages in LLM-compatible format."""
        return [m.to_dict() for m in self.messages]

    def clear(self) -> None:
        """Clear all messages except system."""
        if self.messages and self.messages[0].role == MessageRole.SYSTEM:
            self.messages = [self.messages[0]]
        else:
            self.messages = []


class ToolExecutor:
    """
    Unified tool execution interface.

    Supports:
    - Function tools (Python callables)
    - OpenBench Tool abstractions
    - Dynamic tool registration
    """

    def __init__(self):
        self._tools: Dict[str, Union[Tool, Callable]] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        tool: Union[Tool, Callable],
        schema: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> None:
        """
        Register a tool.

        Args:
            name: Tool name
            tool: Tool instance or callable
            schema: JSON schema for parameters (auto-generated for callables)
            description: Tool description
        """
        self._tools[name] = tool

        if isinstance(tool, Tool):
            self._schemas[name] = tool.get_schema()
        elif schema:
            self._schemas[name] = schema
        else:
            # Generate basic schema from callable
            self._schemas[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description or tool.__doc__ or f"Execute {name}",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }

    def register_from_list(self, tools: List[Union[Tool, Callable]]) -> None:
        """Register multiple tools."""
        for tool in tools:
            if isinstance(tool, Tool):
                self.register(tool.name, tool)
            elif callable(tool):
                self.register(tool.__name__, tool)

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Get all tool schemas for LLM."""
        return list(self._schemas.values())

    def execute(self, name: str, **params) -> Any:
        """
        Execute a tool by name.

        Args:
            name: Tool name
            **params: Tool parameters

        Returns:
            Tool execution result
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        if isinstance(tool, Tool):
            return tool.execute(**params)
        elif callable(tool):
            return tool(**params)

        raise ValueError(f"Invalid tool type: {type(tool)}")

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    max_iterations: int = 10
    system_prompt: Optional[str] = None
    stop_sequences: List[str] = field(default_factory=list)


class BaseAgent(Agent):
    """
    Framework-agnostic base agent implementation.

    Works with any LLM provider through ProviderService.
    Supports tool use, memory, and iterative execution.

    Example:
        >>> agent = BaseAgent(
        ...     goal="Analyze sales data",
        ...     tools=[search_tool, calculate_tool],
        ...     model="gpt-4o"
        ... )
        >>> result = agent.execute(context)
    """

    def __init__(
        self,
        goal: str,
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_iterations: int = 10,
        system_prompt: Optional[str] = None,
        provider_name: Optional[str] = None,
    ):
        """
        Initialize agent.

        Args:
            goal: Agent's objective
            tools: Available tools
            model: LLM model to use
            temperature: Model temperature
            max_iterations: Max tool call iterations
            system_prompt: Custom system prompt (optional)
            provider_name: Specific provider name (uses default if None)
        """
        self.goal = goal
        self.model = model
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.provider_name = provider_name

        # Initialize tool executor
        self.tools = ToolExecutor()
        if tools:
            self.tools.register_from_list(tools)

        # Initialize memory
        self.memory = AgentMemory()

        # Set system prompt
        self._system_prompt = system_prompt or self._default_system_prompt()
        self.memory.add_system(self._system_prompt)

        # LLM provider (lazy loaded)
        self._llm: Optional[LLMProvider] = None

    @property
    def agent_type(self) -> str:
        """Agent type identifier."""
        return "base"

    def _default_system_prompt(self) -> str:
        """Generate default system prompt."""
        return f"""You are an AI assistant with the goal: {self.goal}

You have access to tools to help accomplish your task.
Think step by step and use tools when needed.
Provide clear, actionable responses."""

    def _get_llm(self) -> LLMProvider:
        """Get LLM provider instance."""
        if self._llm is None:
            service = get_provider_service()
            self._llm = service.resolve(
                ProviderType.LLM,
                name=self.provider_name,
                model=self.model,
                temperature=self.temperature,
            )
        return self._llm

    def _parse_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        """Parse tool calls from LLM response."""
        # Handle different response formats
        if hasattr(response, "tool_calls") and response.tool_calls:
            return [
                {
                    "id": tc.id if hasattr(tc, "id") else f"call_{i}",
                    "name": tc.function.name if hasattr(tc, "function") else tc.get("name"),
                    "arguments": (
                        json.loads(tc.function.arguments)
                        if hasattr(tc, "function")
                        else tc.get("arguments", {})
                    ),
                }
                for i, tc in enumerate(response.tool_calls)
            ]
        return []

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """
        Execute the agent's task.

        Implements iterative tool use loop:
        1. Send messages to LLM
        2. If tool calls, execute tools and add results
        3. Repeat until no tool calls or max iterations

        Args:
            context: Execution context with data and configuration

        Returns:
            ExecutionResult with agent's output
        """
        # Add user message with context
        user_message = f"Goal: {context.goal}"
        if context.data:
            user_message += f"\n\nContext data:\n{json.dumps(context.data, indent=2, default=str)}"
        self.memory.add_user(user_message)

        total_tokens = 0
        total_cost = 0.0
        iterations = 0

        try:
            llm = self._get_llm()

            while iterations < self.max_iterations:
                iterations += 1

                # Generate response
                response = llm.generate(
                    prompt=self.memory.get_messages(),
                    model=self.model,
                    tools=self.tools.get_schemas() if len(self.tools) > 0 else None,
                    temperature=self.temperature,
                )

                total_tokens += response.tokens_used
                total_cost += response.cost

                # Check for tool calls
                tool_calls = self._parse_tool_calls(response)

                if not tool_calls:
                    # No tool calls - we're done
                    self.memory.add_assistant(response.text)
                    break

                # Execute tool calls
                self.memory.add_assistant(response.text, tool_calls=tool_calls)

                for tc in tool_calls:
                    try:
                        result = self.tools.execute(tc["name"], **tc["arguments"])
                        result_str = json.dumps(result, default=str)
                    except Exception as e:
                        result_str = f"Error: {str(e)}"

                    self.memory.add_tool_result(tc["id"], tc["name"], result_str)

            return ExecutionResult(
                output=response.text,
                status="completed",
                metadata={
                    "iterations": iterations,
                    "model": self.model,
                    "tools_used": [tc["name"] for tc in tool_calls] if tool_calls else [],
                },
                cost=total_cost,
                tokens_used=total_tokens,
            )

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return ExecutionResult(
                output=None,
                status="failed",
                metadata={"error": str(e), "iterations": iterations},
                cost=total_cost,
                tokens_used=total_tokens,
            )

    def estimate_cost(self, context: ExecutionContext) -> float:
        """Estimate execution cost."""
        config = get_config()
        model_info = config.get_model(self.model)

        if not model_info:
            return 0.0

        # Rough estimate: 1000 tokens input, 500 tokens output per iteration
        estimated_input = 1000 * self.max_iterations
        estimated_output = 500 * self.max_iterations

        return (
            estimated_input * model_info.cost_per_1k_input / 1000
            + estimated_output * model_info.cost_per_1k_output / 1000
        )

    def reset(self) -> None:
        """Reset agent state."""
        self.memory.messages = []
        self.memory.add_system(self._system_prompt)


class SimpleAgent(BaseAgent):
    """
    Simple agent without tool use.

    For straightforward tasks that don't require tools.
    """

    @property
    def agent_type(self) -> str:
        return "simple"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute without tool loop."""
        user_message = f"Goal: {context.goal}"
        if context.data:
            user_message += f"\n\nContext data:\n{json.dumps(context.data, indent=2, default=str)}"
        self.memory.add_user(user_message)

        try:
            llm = self._get_llm()
            response = llm.generate(
                prompt=self.memory.get_messages(),
                model=self.model,
                temperature=self.temperature,
            )

            self.memory.add_assistant(response.text)

            return ExecutionResult(
                output=response.text,
                status="completed",
                metadata={"model": self.model},
                cost=response.cost,
                tokens_used=response.tokens_used,
            )

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return ExecutionResult(
                output=None,
                status="failed",
                metadata={"error": str(e)},
            )


class StructuredOutputAgent(BaseAgent):
    """
    Agent that outputs structured data (JSON).

    Useful for extraction, classification, and data processing tasks.
    """

    def __init__(
        self,
        goal: str,
        output_schema: Dict[str, Any],
        **kwargs,
    ):
        """
        Initialize structured output agent.

        Args:
            goal: Agent's objective
            output_schema: JSON schema for expected output
            **kwargs: BaseAgent arguments
        """
        super().__init__(goal=goal, **kwargs)
        self.output_schema = output_schema

        # Update system prompt to include schema
        schema_str = json.dumps(output_schema, indent=2)
        self._system_prompt = f"""You are an AI assistant with the goal: {goal}

You must respond with valid JSON matching this schema:
{schema_str}

Do not include any text outside the JSON object."""
        # Replace the system message with schema-aware prompt
        self.memory.messages = []
        self.memory.add_system(self._system_prompt)

    @property
    def agent_type(self) -> str:
        return "structured"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute and parse structured output."""
        result = super().execute(context)

        if result.status == "completed" and result.output:
            try:
                # Parse JSON from response
                output_text = result.output
                # Handle markdown code blocks
                if "```json" in output_text:
                    output_text = output_text.split("```json")[1].split("```")[0]
                elif "```" in output_text:
                    output_text = output_text.split("```")[1].split("```")[0]

                parsed = json.loads(output_text.strip())
                result.output = parsed
                result.metadata["parsed"] = True
            except json.JSONDecodeError as e:
                result.metadata["parse_error"] = str(e)
                result.metadata["parsed"] = False

        return result
