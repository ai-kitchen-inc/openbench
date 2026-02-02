"""
Framework-Agnostic Agent Interface for OpenBench.

Provides:
- BaseAgent: Framework-agnostic agent implementation
- SimpleAgent: Agent without tool use
- StructuredOutputAgent: Agent that outputs structured JSON
- ToolExecutor: Unified tool execution interface
- AgentMemory: Conversation and context memory

This decouples agents from specific frameworks (Mastra, LangChain, etc.)
while maintaining compatibility with any LLM provider.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
import json
import logging

from openbench.core.abstractions import (
    Agent,
    DataStore,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    Query,
    Tool,
)
from openbench.core.config import get_config, get_default_model
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

    model: str = field(default_factory=get_default_model)
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
        ...     model="gpt-4o"  # or None to use config default
        ... )
        >>> result = agent.execute(context)
    """

    def __init__(
        self,
        goal: str,
        tools: Optional[List[Union[Tool, Callable]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_iterations: int = 10,
        system_prompt: Optional[str] = None,
        provider_name: Optional[str] = None,
        store: Optional[DataStore] = None,
        retrieval_top_k: int = 5,
        retrieval_threshold: float = 0.0,
    ):
        """
        Initialize agent.

        Args:
            goal: Agent's objective
            tools: Available tools
            model: LLM model to use (defaults to config llm.default_model)
            temperature: Model temperature
            max_iterations: Max tool call iterations
            system_prompt: Custom system prompt (optional)
            provider_name: Specific provider name (uses default if None)
            store: Optional DataStore for RAG (retrieval-augmented generation)
            retrieval_top_k: Number of results to retrieve from store
            retrieval_threshold: Minimum score threshold for retrieved results
        """
        self.goal = goal
        self.model = model or get_default_model()
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.provider_name = provider_name

        # RAG configuration
        self.store = store
        self.retrieval_top_k = retrieval_top_k
        self.retrieval_threshold = retrieval_threshold

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

    def _retrieve_context(self, query_text: str) -> List[Dict[str, Any]]:
        """Retrieve relevant context from store for RAG.

        Args:
            query_text: Text to search for relevant context.

        Returns:
            List of retrieved items with content and metadata.
        """
        if not self.store:
            return []

        try:
            results = self.store.search(Query(
                text=query_text,
                limit=self.retrieval_top_k,
            ))

            # Filter by threshold and extract content
            retrieved = []
            for item, score in zip(results.items, results.scores):
                if score >= self.retrieval_threshold:
                    retrieved.append({
                        "content": item.get("content", ""),
                        "score": score,
                        "metadata": item.get("metadata", {}),
                    })

            return retrieved

        except Exception as e:
            logger.warning(f"Failed to retrieve context from store: {e}")
            return []

    def _augment_context_with_rag(
        self,
        context: ExecutionContext,
        retrieved: List[Dict[str, Any]]
    ) -> ExecutionContext:
        """Augment execution context with retrieved RAG context.

        Args:
            context: Original execution context.
            retrieved: Retrieved items from store.

        Returns:
            Augmented execution context.
        """
        if not retrieved:
            return context

        # Build RAG context string
        rag_context_parts = []
        for i, item in enumerate(retrieved, 1):
            rag_context_parts.append(
                f"[Source {i}] (relevance: {item['score']:.2f})\n{item['content']}"
            )

        rag_context = "\n\n---\n\n".join(rag_context_parts)

        # Augment context data
        augmented_data = context.data or {}
        if isinstance(augmented_data, dict):
            augmented_data = {
                **augmented_data,
                "_rag_context": rag_context,
                "_rag_sources": len(retrieved),
            }
        else:
            augmented_data = {
                "original_data": augmented_data,
                "_rag_context": rag_context,
                "_rag_sources": len(retrieved),
            }

        return ExecutionContext(
            goal=context.goal,
            data=augmented_data,
            tools=context.tools,
            memory=context.memory,
            constraints=context.constraints,
        )

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
        1. Retrieve relevant context from store (if configured)
        2. Send messages to LLM
        3. If tool calls, execute tools and add results
        4. Repeat until no tool calls or max iterations

        Args:
            context: Execution context with data and configuration

        Returns:
            ExecutionResult with agent's output
        """
        # Retrieve and augment context with RAG if store is configured
        if self.store:
            retrieved = self._retrieve_context(context.goal)
            context = self._augment_context_with_rag(context, retrieved)

        # Add user message with context
        user_message = f"Goal: {context.goal}"
        if context.data:
            # Format RAG context specially if present
            data_to_show = context.data
            if isinstance(data_to_show, dict) and "_rag_context" in data_to_show:
                rag_context = data_to_show.pop("_rag_context", "")
                rag_sources = data_to_show.pop("_rag_sources", 0)
                user_message += f"\n\n## Retrieved Context ({rag_sources} sources):\n{rag_context}"
                if data_to_show:
                    user_message += f"\n\n## Additional Data:\n{json.dumps(data_to_show, indent=2, default=str)}"
            else:
                user_message += f"\n\nContext data:\n{json.dumps(data_to_show, indent=2, default=str)}"
        self.memory.add_user(user_message)

        total_tokens = 0
        total_cost = 0.0
        iterations = 0
        tool_calls: List[Dict[str, Any]] = []
        response = None

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
                output=response.text if response else None,
                status="completed" if response else "no_iterations",
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
