"""
Framework-Agnostic Agent Interface for OpenBench.

Provides:
- BaseAgent: Framework-agnostic agent implementation
- SimpleAgent: Agent without tool use
- StructuredOutputAgent: Agent that outputs structured JSON
- ToolExecutor: Unified tool execution interface
- AgentMemory: Conversation and context memory
- QueryRewriter: LLM-based query enhancement for better RAG retrieval

This decouples agents from specific frameworks (Mastra, LangChain, etc.)
while maintaining compatibility with any LLM provider.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

from openbench.core.abstractions import (
    Agent,
    DataStore,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    LLMResponse,
    MediaContent,
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
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    raw_content: Any = field(default=None, repr=False)
    media: list[MediaContent] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to LLM-compatible format."""
        result = {"role": self.role.value, "content": self.content}
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.raw_content is not None:
            result["raw_content"] = self.raw_content
        if self.media:
            # Provider-neutral media references; each LLMProvider translates
            # these into its own multimodal format in _convert_messages.
            result["media"] = [m.to_dict() for m in self.media]
        return result


@dataclass
class AgentMemory:
    """Agent conversation memory."""

    messages: list[Message] = field(default_factory=list)
    max_messages: int = 100
    max_tokens: int | None = None

    @contextmanager
    def turn(self) -> Iterator[None]:
        """Atomic turn context. Base ``AgentMemory`` is a no-op.

        :class:`PersistentMemory` overrides this to buffer writes during
        the turn and flush atomically at the end, so a process crash
        mid-turn cannot leave the backing store with orphan
        ``tool_calls`` that lack matching tool responses.
        """
        yield

    def _estimate_tokens(self) -> int:
        """Rough token estimate: ~4 chars per token."""
        return sum(len(m.content) // 4 for m in self.messages)

    def _trim_oldest(self, keep_count: int) -> None:
        """Trim oldest messages, preserving system message."""
        if self.messages and self.messages[0].role == MessageRole.SYSTEM:
            self.messages = [self.messages[0], *self.messages[-(keep_count - 1) :]]
        else:
            self.messages = self.messages[-keep_count:]

    def add(self, role: MessageRole, content: str, **kwargs) -> None:
        """Add message to memory."""
        self.messages.append(Message(role=role, content=content, **kwargs))

        # Trim by message count
        if len(self.messages) > self.max_messages:
            self._trim_oldest(self.max_messages)

        # Trim by token budget
        if self.max_tokens and self._estimate_tokens() > self.max_tokens:
            # Remove oldest non-system messages until under budget
            while len(self.messages) > 1 and self._estimate_tokens() > self.max_tokens:
                # Find first non-system message to remove
                for i, m in enumerate(self.messages):
                    if m.role != MessageRole.SYSTEM:
                        self.messages.pop(i)
                        break
                else:
                    break
            # Warn if still over budget (system message alone exceeds limit)
            if self._estimate_tokens() > self.max_tokens:
                logger.warning(
                    "System message alone (~%d tokens) exceeds max_tokens (%d). "
                    "Consider increasing max_tokens or shortening the system prompt.",
                    self._estimate_tokens(),
                    self.max_tokens,
                )

    def add_system(self, content: str) -> None:
        """Add system message."""
        self.add(MessageRole.SYSTEM, content)

    def add_user(self, content: str, media: list[MediaContent] | None = None) -> None:
        """Add user message, optionally with provider-neutral media references."""
        self.add(MessageRole.USER, content, media=media)

    def add_assistant(
        self,
        content: str,
        tool_calls: list[dict] | None = None,
        raw_content: Any = None,
    ) -> None:
        """Add assistant message."""
        self.add(
            MessageRole.ASSISTANT,
            content,
            tool_calls=tool_calls,
            raw_content=raw_content,
        )

    def add_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        """Add tool result message."""
        self.add(MessageRole.TOOL, result, name=name, tool_call_id=tool_call_id)

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages in LLM-compatible format."""
        return [m.to_dict() for m in self.messages]

    def clear(self) -> None:
        """Clear all messages except system."""
        if self.messages and self.messages[0].role == MessageRole.SYSTEM:
            self.messages = [self.messages[0]]
        else:
            self.messages = []

    def truncate_to(self, length: int) -> None:
        """Truncate message history to the given length.

        Subclasses that persist messages (e.g. ``PersistentMemory``) must
        override this so the persistent store is kept in sync — otherwise
        rollback after a failed turn only affects the in-memory list and
        orphaned messages will resurface when the session is reloaded.

        Args:
            length: Number of messages to keep from the start. Must be >= 0.
                Values larger than the current length are a no-op.
        """
        if length < 0:
            length = 0
        if length < len(self.messages):
            self.messages = self.messages[:length]


class ToolExecutor:
    """
    Unified tool execution interface.

    Supports:
    - Function tools (Python callables)
    - OpenBench Tool abstractions
    - Dynamic tool registration
    """

    def __init__(self):
        self._tools: dict[str, Tool | Callable] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        tool: Tool | Callable,
        schema: dict[str, Any] | None = None,
        description: str | None = None,
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
            # Generate schema from callable using inspect.signature()
            properties = {}
            required = []
            if callable(tool):
                type_map = {
                    str: "string",
                    int: "integer",
                    float: "number",
                    bool: "boolean",
                }
                try:
                    sig = inspect.signature(tool)
                    for param_name, param in sig.parameters.items():
                        prop = {"type": "string"}
                        if param.annotation != inspect.Parameter.empty:
                            prop["type"] = type_map.get(param.annotation, "string")
                        if param.default != inspect.Parameter.empty:
                            prop["default"] = param.default
                        properties[param_name] = prop
                        if param.default == inspect.Parameter.empty:
                            required.append(param_name)
                except (ValueError, TypeError):
                    pass

            self._schemas[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description or tool.__doc__ or f"Execute {name}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }

    def register_from_list(self, tools: list[Tool | Callable]) -> None:
        """Register multiple tools."""
        for tool in tools:
            if isinstance(tool, Tool):
                self.register(tool.name, tool)
            elif callable(tool):
                self.register(tool.__name__, tool)

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get all tool schemas for LLM."""
        return list(self._schemas.values())

    def execute(self, name: str, timeout: int | float | None = None, **params) -> Any:
        """
        Execute a tool by name.

        Args:
            name: Tool name
            timeout: Maximum execution time in seconds. When omitted, tools may
                provide a ``timeout_seconds`` attribute; otherwise defaults to 30.
            **params: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found or invalid type
            TimeoutError: If tool execution exceeds timeout
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")
        resolved_timeout = timeout
        if resolved_timeout is None:
            resolved_timeout = getattr(tool, "timeout_seconds", 30)
        try:
            resolved_timeout = float(resolved_timeout)
        except (TypeError, ValueError):
            resolved_timeout = 30.0

        import contextvars
        from queue import Empty, SimpleQueue

        # Use a queue for thread-safe result passing (one per call).
        q: SimpleQueue = SimpleQueue()

        def _run():
            try:
                if isinstance(tool, Tool):
                    q.put(("ok", tool.execute(**params)))
                elif callable(tool):
                    q.put(("ok", tool(**params)))
                else:
                    q.put(("err", ValueError(f"Invalid tool type: {type(tool)}")))
            except Exception as e:
                q.put(("err", e))

        # Propagate ContextVar values so tool functions can access
        # per-request state (e.g. render items, attachments).
        ctx = contextvars.copy_context()
        thread = threading.Thread(target=ctx.run, args=(_run,), daemon=True)
        thread.start()
        thread.join(timeout=resolved_timeout)

        if thread.is_alive():
            raise TimeoutError(f"Tool '{name}' exceeded {resolved_timeout:g}s timeout")

        try:
            status, value = q.get_nowait()
        except Empty:
            raise TimeoutError(f"Tool '{name}' finished but produced no result") from None
        if status == "err":
            raise value

        return value

    def execute_parallel(
        self, calls: list[dict[str, Any]], timeout: int | float | None = None
    ) -> list[dict[str, Any]]:
        """Execute multiple tool calls concurrently.

        Independent tool calls run in separate threads for faster execution.
        Each call has its own timeout. One failure does not block others.

        Context propagation: each thread receives a copy of the calling
        context (via ``contextvars.copy_context()``) so that ContextVar
        values (e.g. per-request render items) are visible to tool functions.

        Args:
            calls: List of tool call dicts with ``name``, ``arguments``, ``id``.
            timeout: Maximum execution time per tool in seconds. When omitted,
                each tool may provide its own ``timeout_seconds``.

        Returns:
            List of result dicts with ``call``, ``result``, ``error`` keys.
            Order matches the input ``calls`` order.
        """
        import concurrent.futures
        import contextvars

        results: dict[int, dict[str, Any]] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
            future_to_idx = {
                pool.submit(
                    contextvars.copy_context().run,
                    self.execute,
                    call["name"],
                    timeout=timeout,
                    **call["arguments"],
                ): idx
                for idx, call in enumerate(calls)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                    results[idx] = {
                        "call": calls[idx],
                        "result": result,
                        "error": None,
                    }
                except Exception as e:
                    results[idx] = {
                        "call": calls[idx],
                        "result": None,
                        "error": str(e),
                    }

        # Return in original order
        return [results[i] for i in range(len(calls))]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    model: str = field(default_factory=get_default_model)
    temperature: float = 0.7
    max_tokens: int | None = None
    max_iterations: int = 10
    system_prompt: str | None = None
    stop_sequences: list[str] = field(default_factory=list)


@dataclass
class ProgressEvent:
    """Progress update from agent execution.

    Emitted via ``on_progress`` callback during BaseAgent.execute() to report
    sub-phases (planning, tool use, analysis) for real-time UI indicators.
    """

    phase: str
    detail: str = ""


class QueryRewriter:
    """LLM-based query rewriter for improved RAG retrieval.

    Rewrites user queries into multiple optimized search queries
    to improve semantic search recall.

    Example:
        >>> rewriter = QueryRewriter(llm_provider)
        >>> queries = rewriter.rewrite("How does photosynthesis affect climate?")
        >>> # ["photosynthesis carbon dioxide absorption", "climate change CO2 cycle", ...]
    """

    def __init__(self, llm: LLMProvider, model: str | None = None):
        self.llm = llm
        self.model = model

    def rewrite(self, query: str, context: str = "") -> list[str]:
        """Rewrite a query into 1-3 optimized search queries.

        Args:
            query: Original user query.
            context: Optional additional context to inform rewriting.

        Returns:
            List of rewritten search queries (1-3 items).
            Falls back to [query] on failure.
        """
        prompt = (
            "Given the user query below, generate 1 to 3 search queries optimized for "
            "semantic search over a document knowledge base. Each query should target "
            "a different aspect of the information need.\n\n"
            f"User query: {query}\n"
        )
        if context:
            prompt += f"Additional context: {context}\n"
        prompt += '\nRespond with ONLY a JSON array of strings, e.g. ["query1", "query2"].'

        try:
            response = self.llm.generate(prompt=prompt, model=self.model, temperature=0.3)
            text = response.text.strip()
            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            queries = json.loads(text)
            if isinstance(queries, list) and queries and all(isinstance(q, str) for q in queries):
                return queries[:3]  # Cap at 3
        except Exception as e:
            logger.warning(f"Query rewriting failed, using original query: {e}")

        return [query]


def _emit_progress(
    on_progress: Callable[[ProgressEvent], None] | None,
    phase: str,
    detail: str = "",
) -> None:
    """Safely emit a progress event if callback is provided."""
    if on_progress:
        on_progress(ProgressEvent(phase=phase, detail=detail))


def _sanitize_for_json(value: Any) -> Any:
    """Recursively replace non-finite floats with None so the result is strict JSON.

    Python's ``json.dumps`` emits ``NaN`` / ``Infinity`` / ``-Infinity`` as
    bareword literals by default (``allow_nan=True``). Those are NOT valid
    per RFC 8259, and Gemini's API rejects the payload with
    ``INVALID_ARGUMENT: Invalid JSON payload received. Unexpected token``.

    Tool implementations that touch pandas / numpy (e.g. the xql skill)
    frequently return ``float('nan')`` for empty cells, which surfaces the
    problem on the very first tool result put into agent memory. Walk the
    structure once and convert those to ``None`` before serialization so
    every downstream JSON encoder sees strict JSON.
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return value


def _tool_result_to_json(result: Any) -> str:
    """Serialize a tool result as strict JSON that Gemini will accept.

    Sanitizes NaN/Infinity to ``None``, then dumps with ``allow_nan=False``
    so we fail loudly if some other non-finite value slips through instead
    of silently writing invalid JSON.
    """
    sanitized = _sanitize_for_json(result)
    try:
        return json.dumps(sanitized, default=str, allow_nan=False)
    except ValueError as e:
        # Last-resort fallback: stringify the whole result. Better to send
        # a lossy text blob than to crash the agent turn on a single weird
        # value deep inside the structure.
        logger.warning("Tool result still contained non-finite values after sanitize: %s", e)
        return json.dumps(str(result), default=str, allow_nan=False)


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
        tools: list[Tool | Callable] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_iterations: int = 10,
        system_prompt: str | None = None,
        persona: Any = None,
        skills: list[str | Path] | None = None,
        provider_name: str | None = None,
        store: DataStore | None = None,
        retrieval_top_k: int = 5,
        retrieval_threshold: float = 0.0,
        query_rewriter: bool = False,
        multi_hop_rag: bool = False,
        enable_planning: bool = False,
        parallel_tool_execution: bool = False,
        memory_store: Any = None,
        session_id: str | None = None,
        scratchpad: Any = None,
        output_store: Any = None,
        output_url_base: str | None = None,
    ):
        """
        Initialize agent.

        Args:
            goal: Agent's objective
            tools: Available tools
            model: LLM model to use (defaults to config llm.default_model)
            temperature: Model temperature
            max_iterations: Max tool call iterations
            system_prompt: Custom system prompt string (optional, legacy)
            persona: Agent persona — any of:
                - Path/str pointing to a ``soul/`` directory (filesystem).
                - A :class:`Persona` instance (pre-composed).
                - A :class:`PersonaSource` instance (Drive, HTTP, inline, etc.).
                When provided, takes precedence over system_prompt= and composes
                SOUL.md + STYLE.md + AGENTS.md into the system prompt.
            skills: List of skill names or directory paths. SDK skill names
                (e.g. "data-visualization") are resolved from
                src/openbench/skills/. Directory paths (e.g. "skills/ldi-parser")
                are loaded as project skills and override SDK skills of the
                same name. Each skill's context is appended to the system
                prompt after the persona, and its tools.py functions are
                auto-registered with the agent's ToolExecutor.
            provider_name: Specific provider name (uses default if None)
            store: Optional DataStore for RAG (retrieval-augmented generation)
            retrieval_top_k: Number of results to retrieve from store
            retrieval_threshold: Minimum score threshold for retrieved results
            query_rewriter: Enable LLM-based query rewriting for better retrieval
            multi_hop_rag: Enable tool-based multi-hop retrieval (agent decides
                when to search). When True, auto-retrieval at start is skipped and
                a ``retrieve_knowledge`` tool is registered instead.
            enable_planning: Enable task decomposition before execution.
                Uses LLM to break complex goals into step-by-step plans.
            parallel_tool_execution: Execute multiple tool calls concurrently.
                When True, independent tool calls within a single iteration
                run in parallel threads instead of sequentially.
            memory_store: Optional MemoryStore for persistent conversation memory.
                When provided with session_id, uses PersistentMemory instead of
                in-memory AgentMemory.
            session_id: Session identifier for persistent memory. Required when
                memory_store is provided.
            scratchpad: Optional ScratchpadStore for user-editable markdown
                memory. When provided, it is injected into any loaded skill
                whose ``tools.py`` declares a ``bind(scratchpad=...)``
                function — e.g. the bundled ``memory-scratchpad`` skill.
        """
        self.goal = goal
        self.model = model or get_default_model()
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.provider_name = provider_name
        self.enable_planning = enable_planning
        self.parallel_tool_execution = parallel_tool_execution
        self._scratchpad = scratchpad

        # RAG configuration
        self.store = store
        self.retrieval_top_k = retrieval_top_k
        self.retrieval_threshold = retrieval_threshold
        self._query_rewriter_enabled = query_rewriter
        self._query_rewriter: QueryRewriter | None = None
        self.multi_hop_rag = multi_hop_rag

        # Initialize tool executor
        self.tools = ToolExecutor()
        if tools:
            self.tools.register_from_list(tools)

        # Auto-register RAG tool for multi-hop retrieval
        if store and multi_hop_rag:
            self.tools.register(
                "retrieve_knowledge",
                self._rag_tool_retrieve,
                schema={
                    "type": "function",
                    "function": {
                        "name": "retrieve_knowledge",
                        "description": (
                            "Search the knowledge base for relevant information. "
                            "Use when you need more context to answer the question. "
                            "You can call this multiple times with different queries."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query for the knowledge base",
                                }
                            },
                            "required": ["query"],
                        },
                    },
                },
            )

        # Initialize memory (persistent or in-memory)
        if memory_store is not None or session_id is not None:
            if memory_store is None or session_id is None:
                raise ValueError(
                    f"Both 'memory_store' and 'session_id' must be provided together "
                    f"for persistent memory. Got memory_store="
                    f"{type(memory_store).__name__ if memory_store else None!r}, "
                    f"session_id={session_id!r}."
                )
            from openbench.intelligence.memory import PersistentMemory

            self.memory = PersistentMemory(store=memory_store, session_id=session_id)
        else:
            self.memory = AgentMemory()

        # Resolve persona to system_prompt (persona takes precedence)
        self._persona = None
        if persona is not None:
            from pathlib import Path

            from openbench.intelligence.persona import Persona
            from openbench.intelligence.persona_source import PersonaSource

            if system_prompt:
                import warnings

                warnings.warn(
                    "Both persona= and system_prompt= provided. "
                    "persona= takes precedence; system_prompt= is ignored.",
                    UserWarning,
                    stacklevel=2,
                )
            if isinstance(persona, (str, Path)):
                self._persona = Persona.from_dir(persona)
            elif isinstance(persona, Persona):
                self._persona = persona
            elif isinstance(persona, PersonaSource):
                self._persona = Persona.from_source(persona)
            else:
                raise TypeError(
                    f"persona must be str, Path, Persona, or PersonaSource instance, "
                    f"got {type(persona).__name__}"
                )
            # Fix #2: persona= explicitly sets identity — no fallback to default
            self._system_prompt = self._persona.compose()
            logger.info(
                "Persona loaded from %s (SOUL: %d chars, STYLE: %d chars, AGENTS: %d chars)",
                self._persona.source,
                len(self._persona.soul),
                len(self._persona.style),
                len(self._persona.agents),
            )
        elif system_prompt:
            self._system_prompt = system_prompt
        else:
            self._system_prompt = self._default_system_prompt()

        # Resolve skills — composed AFTER persona so skill context appends to
        # the base identity. SDK skills are auto-discovered; named references
        # and path references in `skills=` are both supported.
        self._skill_registry = None
        if skills:
            from openbench.intelligence.skill_registry import SkillRegistry

            self._skill_registry = SkillRegistry()
            self._skill_registry.load_sdk_skills()
            self._skill_registry.load_user_skills()
            self._skill_registry.load_skills(skills)

            # Inject agent-scoped runtime state into any skill that declares
            # a module-level ``bind(**kwargs)`` function in its tools.py.
            # Skills that do not declare ``bind`` are silently skipped. This
            # is how the bundled ``memory-scratchpad`` skill learns which
            # ScratchpadStore to use (see §6 of the storage-layer RFC), and
            # how ``export-excel`` learns where downloadable artifacts land.
            bind_kwargs: dict[str, Any] = {}
            if scratchpad is not None:
                bind_kwargs["scratchpad"] = scratchpad
            if output_store is not None:
                bind_kwargs["output_store"] = output_store
            if output_url_base is not None:
                bind_kwargs["output_url_base"] = output_url_base
            if bind_kwargs:
                self._skill_registry.bind(**bind_kwargs)

            skill_context = self._skill_registry.compose_context()
            if skill_context:
                self._system_prompt = f"{self._system_prompt}\n\n{skill_context}"

            # Register every tool exposed by the loaded skills. Collisions
            # with existing tools raise — the caller must rename or exclude.
            for tool_name, tool_fn, tool_schema in self._skill_registry.collect_tools():
                if tool_name in self.tools._tools:
                    raise ValueError(
                        f"Tool '{tool_name}' from skill conflicts with an "
                        f"existing tool of the same name. Rename one of them."
                    )
                self.tools.register(tool_name, tool_fn, schema=tool_schema)

            skill_summary = self._skill_registry.summary()
            logger.info(
                "Skills loaded: %d SDK + %d user + %d project (total context: %d chars, tools: %d)",
                len(skill_summary["sdk_skills"]),
                len(skill_summary["user_skills"]),
                len(skill_summary["project_skills"]),
                skill_summary["context_chars"],
                skill_summary["total_tools"],
            )

        # Token budget warning (RFC §8.3, R3: "2K chars warn, non-fatal")
        _TOKEN_BUDGET_WARNING_CHARS = 8000
        prompt_len = len(self._system_prompt)
        if prompt_len > _TOKEN_BUDGET_WARNING_CHARS:
            logger.warning(
                "System prompt is %d chars (~%d tokens). Large prompts increase "
                "latency and cost. Consider reducing persona/skill content or "
                "using lazy skill loading (Strategy B).",
                prompt_len,
                prompt_len // 4,
            )
        else:
            logger.info(
                "System prompt composed: %d chars (~%d tokens)", prompt_len, prompt_len // 4
            )

        # Add system message to memory.
        # Fix #1: when persona= is provided, it represents the authoritative
        # current identity — replace any existing system message from a
        # resumed PersistentMemory session, even if persona files have changed.
        if persona is not None:
            if self.memory.messages and self.memory.messages[0].role == MessageRole.SYSTEM:
                # Replace existing system message in-place
                self.memory.messages[0] = Message(
                    role=MessageRole.SYSTEM, content=self._system_prompt
                )
            else:
                self.memory.add_system(self._system_prompt)
        elif not self.memory.messages or self.memory.messages[0].role != MessageRole.SYSTEM:
            # Legacy path: only add if no system message exists yet
            self.memory.add_system(self._system_prompt)

        # LLM provider (lazy loaded)
        self._llm: LLMProvider | None = None

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

    def _run_planning(self, context: ExecutionContext) -> None:
        """Run task planning phase and inject plan into memory.

        Passes recent conversation context to the planner so that follow-up
        requests (e.g. "create table" after a search) produce context-aware plans.

        Args:
            context: Execution context containing the goal.
        """
        from openbench.intelligence.planning import TaskPlanner

        try:
            planner = TaskPlanner(self._get_llm(), self.model)
            tool_names = list(self.tools._tools.keys()) if len(self.tools) > 0 else []
            conversation_context = self._get_recent_context()
            plan = planner.plan(context.goal, tool_names, conversation_context)
            if plan.steps:
                plan_prompt = planner.format_plan_prompt(plan)
                self.memory.add_system(plan_prompt)
                logger.info(f"Planning produced {len(plan.steps)} steps")
        except Exception as e:
            logger.warning(f"Planning phase failed, continuing without plan: {e}")

    def _get_recent_context(self) -> str:
        """Build a summary of recent conversation for planning context.

        Returns recent user and assistant messages (up to 6), truncated to
        keep the planning prompt concise.
        """
        recent: list[str] = []
        for msg in reversed(self.memory.messages):
            if msg.role == MessageRole.SYSTEM:
                continue
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT) and msg.content:
                label = "User" if msg.role == MessageRole.USER else "Assistant"
                content = msg.content[:300]
                if len(msg.content) > 300:
                    content += "..."
                recent.append(f"{label}: {content}")
            if len(recent) >= 6:
                break
        if not recent:
            return ""
        return "\n".join(reversed(recent))

    def _get_query_rewriter(self) -> QueryRewriter | None:
        """Get query rewriter, lazily initialized."""
        if not self._query_rewriter_enabled:
            return None
        if self._query_rewriter is None:
            self._query_rewriter = QueryRewriter(self._get_llm(), self.model)
        return self._query_rewriter

    def _rag_tool_retrieve(self, query: str) -> str:
        """Tool function for multi-hop RAG retrieval.

        Called by the agent's reasoning loop via the ``retrieve_knowledge`` tool.

        Args:
            query: Search query for the knowledge base.

        Returns:
            Formatted string with retrieved chunks, or a "not found" message.
        """
        if not self.store:
            return "No knowledge base configured."

        results = self._retrieve_context(query)
        if not results:
            return "No relevant documents found for this query."

        parts = []
        for i, item in enumerate(results, 1):
            parts.append(f"[Source {i}] (relevance: {item['score']:.2f})\n{item['content']}")
        return "\n\n---\n\n".join(parts)

    def _retrieve_context(self, query_text: str) -> list[dict[str, Any]]:
        """Retrieve relevant context from store for RAG.

        Supports query rewriting: when enabled, the query is rewritten into
        1-3 optimized queries and results are deduplicated.

        Args:
            query_text: Text to search for relevant context.

        Returns:
            List of retrieved items with content and metadata.
        """
        if not self.store:
            return []

        try:
            rewriter = self._get_query_rewriter()
            queries = rewriter.rewrite(query_text) if rewriter else [query_text]

            # Retrieve for each query, deduplicate by content hash
            all_retrieved: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            for q in queries:
                results = self.store.search(Query(text=q, limit=self.retrieval_top_k))

                for item, score in zip(results.items, results.scores, strict=True):
                    if score < self.retrieval_threshold:
                        continue
                    item_id = item.get("id", item.get("content", "")[:100])
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    all_retrieved.append(
                        {
                            "content": item.get("content", ""),
                            "score": score,
                            "metadata": item.get("metadata", {}),
                        }
                    )

            # Sort by score descending, cap at top_k
            all_retrieved.sort(key=lambda x: x["score"], reverse=True)
            return all_retrieved[: self.retrieval_top_k]

        except Exception as e:
            logger.warning(f"Failed to retrieve context from store: {e}")
            return []

    def _augment_context_with_rag(
        self, context: ExecutionContext, retrieved: list[dict[str, Any]]
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

    def _parse_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        """Parse tool calls from LLM response."""
        if not (hasattr(response, "tool_calls") and response.tool_calls):
            return []

        parsed = []
        for i, tc in enumerate(response.tool_calls):
            call_id = tc.id if hasattr(tc, "id") else f"call_{i}"

            if hasattr(tc, "function"):
                name = tc.function.name
                raw_args = tc.function.arguments
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            f"Failed to parse tool arguments for '{name}', using empty dict"
                        )
                        args = {}
                else:
                    args = raw_args if raw_args else {}
            else:
                name = tc.get("name")
                args = tc.get("arguments", {})

            parsed.append({"id": call_id, "name": name, "arguments": args})

        return parsed

    def execute(
        self,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> ExecutionResult:
        """
        Execute the agent's task.

        Implements iterative tool use loop:
        1. Retrieve relevant context from store (if configured)
        2. Send messages to LLM
        3. If tool calls, execute tools and add results
        4. Repeat until no tool calls or max iterations

        Args:
            context: Execution context with data and configuration
            on_chunk: Optional callback invoked with each text delta during
                streaming. When provided and the LLM provider supports
                generate_stream(), tokens are streamed progressively.
            on_progress: Optional callback invoked with ProgressEvent to report
                sub-phases (planning, RAG retrieval, tool execution) for
                real-time UI progress indicators.

        Returns:
            ExecutionResult with agent's output
        """
        # Planning phase (optional) — decompose goal before execution
        if self.enable_planning:
            _emit_progress(on_progress, "Planning approach")
            self._run_planning(context)

        # Retrieve and augment context with RAG if store is configured.
        # Skip auto-retrieval when multi_hop_rag is enabled — the agent
        # will call retrieve_knowledge tool during the reasoning loop.
        if self.store and not self.multi_hop_rag:
            _emit_progress(on_progress, "Searching knowledge")
            retrieved = self._retrieve_context(context.goal)
            context = self._augment_context_with_rag(context, retrieved)

        # Add user message with context
        user_message = f"Goal: {context.goal}"
        media_payload: list[MediaContent] | None = None
        if context.data:
            # Pull provider-neutral media references out before serializing the
            # rest of the data to text — they travel on the message, not in the
            # JSON blob. Each LLMProvider decides whether to send them natively.
            if isinstance(context.data, dict):
                media_payload = context.data.pop("_media", None) or None
            # Format RAG context specially if present
            data_to_show = context.data
            if isinstance(data_to_show, dict) and "_rag_context" in data_to_show:
                rag_context = data_to_show.pop("_rag_context", "")
                rag_sources = data_to_show.pop("_rag_sources", 0)
                user_message += f"\n\n## Retrieved Context ({rag_sources} sources):\n{rag_context}"
                if data_to_show:
                    user_message += f"\n\n## Additional Data:\n{json.dumps(data_to_show, indent=2, default=str)}"
            elif data_to_show:
                user_message += (
                    f"\n\nContext data:\n{json.dumps(data_to_show, indent=2, default=str)}"
                )
        self.memory.add_user(user_message, media=media_payload)

        import time

        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        iterations = 0
        all_tools_used: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        iteration_stats: list[dict[str, Any]] = []
        response = None
        start_time = time.monotonic()

        # Gemini 3 Confidence Dropout retry: when the model returns
        # no text and no tool calls (all-thought response), retry up
        # to this many times before accepting an empty result. Without
        # this the agent returns a blank answer on the first dropout.
        _MAX_EMPTY_RETRIES = 2
        _empty_retries = 0

        # Determine if we can stream
        use_stream = on_chunk is not None

        try:
            llm = self._get_llm()

            # Run the ReAct loop inside an atomic memory turn. If the
            # process dies or an exception escapes before the assistant
            # final message is appended, the turn rolls back and the
            # store never sees a half-written assistant(tool_calls) row
            # that would poison subsequent requests with Gemini's
            # "function response turn must come immediately after a
            # function call turn" 400. The user-message add (line
            # above) is intentionally OUTSIDE the turn so the user's
            # own text survives a failed turn.
            with self.memory.turn():
                while iterations < self.max_iterations:
                    iterations += 1
                    iter_start = time.monotonic()

                    # Emit progress for LLM call phase
                    if iterations == 1:
                        _emit_progress(on_progress, "Thinking")
                    else:
                        _emit_progress(on_progress, "Analyzing results")

                    gen_kwargs: dict[str, Any] = {
                        "prompt": self.memory.get_messages(),
                        "model": self.model,
                        "tools": self.tools.get_schemas() or None,
                        "temperature": self.temperature,
                    }

                    if use_stream:
                        # Streaming path: yield deltas via on_chunk
                        full_text = ""
                        final_response = None
                        for chunk in llm.generate_stream(**gen_kwargs):
                            if chunk.text:
                                on_chunk(chunk.text)
                                full_text += chunk.text
                            final_response = chunk

                        if final_response is None:
                            response = LLMResponse(
                                text="", model=self.model, tokens_used=0, cost=0.0
                            )
                        else:
                            response = final_response
                            # Ensure full accumulated text (stream yields deltas)
                            if full_text and not getattr(response, "tool_calls", None):
                                response.text = full_text
                    else:
                        # Non-streaming path (backward compatible)
                        response = llm.generate(**gen_kwargs)

                    total_tokens += response.tokens_used
                    total_cost += response.cost

                    # Track per-iteration token breakdown
                    iter_prompt = response.metadata.get("prompt_tokens", 0)
                    iter_completion = response.metadata.get("completion_tokens", 0)
                    total_prompt_tokens += iter_prompt
                    total_completion_tokens += iter_completion

                    # Check for tool calls
                    tool_calls = self._parse_tool_calls(response)

                    iter_stat = {
                        "iteration": iterations,
                        "prompt_tokens": iter_prompt,
                        "completion_tokens": iter_completion,
                        "cost": response.cost,
                        "tool_calls": [tc["name"] for tc in tool_calls],
                        "duration_seconds": round(time.monotonic() - iter_start, 3),
                    }
                    iteration_stats.append(iter_stat)

                    # Get raw content for replaying (preserves thought_signature)
                    raw_content = getattr(response, "raw_content", None)

                    if not tool_calls:
                        # No tool calls. If the model also produced no text this
                        # is a Gemini 3 "Confidence Dropout" — the model spent
                        # thinking tokens but didn't commit to an answer. Retry
                        # instead of accepting a blank result, up to a cap.
                        if not response.text.strip() and _empty_retries < _MAX_EMPTY_RETRIES:
                            _empty_retries += 1
                            diagnostics = response.metadata.get("empty_response_diagnostics")
                            logger.warning(
                                "Empty response on iteration %d (retry %d/%d, diagnostics=%s). "
                                "Retrying — NOT adding empty turn to memory.",
                                iterations,
                                _empty_retries,
                                _MAX_EMPTY_RETRIES,
                                diagnostics,
                            )
                            # Do NOT add the empty response to memory — that would
                            # poison the conversation with a blank assistant turn and
                            # Gemini might follow the pattern. Just retry.
                            continue

                        # Non-empty text OR max retries exhausted — we're done.
                        if not response.text.strip() and _empty_retries >= _MAX_EMPTY_RETRIES:
                            logger.warning(
                                "Empty response persists after %d retries. Accepting empty result.",
                                _MAX_EMPTY_RETRIES,
                            )
                        self.memory.add_assistant(response.text, raw_content=raw_content)
                        break

                    # Execute tool calls.
                    # Snapshot memory length so we can roll back on failure —
                    # without this, a mid-loop exception leaves an orphaned
                    # assistant(tool_calls) message in persistent memory that
                    # Gemini will reject ("function response turn must come
                    # immediately after a function call turn") on every
                    # subsequent request in the same session.
                    all_tools_used.extend(tc["name"] for tc in tool_calls)
                    pre_tools_len = len(self.memory.messages)
                    self.memory.add_assistant(
                        response.text, tool_calls=tool_calls, raw_content=raw_content
                    )

                    # Emit progress with tool names
                    tool_names = [tc["name"] for tc in tool_calls]
                    _emit_progress(on_progress, f"Running {', '.join(tool_names)}")

                    try:
                        if self.parallel_tool_execution and len(tool_calls) > 1:
                            # Parallel execution for multiple tool calls
                            results = self.tools.execute_parallel(tool_calls)
                            for r in results:
                                tc = r["call"]
                                if r["error"] is not None:
                                    result_str = f"Error: {r['error']}"
                                else:
                                    result_str = _tool_result_to_json(r["result"])
                                self.memory.add_tool_result(tc["id"], tc["name"], result_str)
                        else:
                            # Sequential execution (default)
                            for tc in tool_calls:
                                try:
                                    result = self.tools.execute(tc["name"], **tc["arguments"])
                                    result_str = _tool_result_to_json(result)
                                except Exception as e:
                                    result_str = f"Error: {e!s}"
                                self.memory.add_tool_result(tc["id"], tc["name"], result_str)
                    except Exception:
                        # Tool execution loop itself blew up (e.g. memory.add_tool_result
                        # raised on SQLite error). Roll back the half-written turn so
                        # memory stays in a Gemini-acceptable state, then propagate.
                        # NOTE: use truncate_to(), not direct list slicing, so
                        # PersistentMemory can also delete the orphaned rows from
                        # its backing store. A plain slice would leave the assistant
                        # (tool_calls=...) message in SQLite where it resurrects on
                        # the next session load and retriggers the same Gemini error.
                        self.memory.truncate_to(pre_tools_len)
                        raise

            total_duration = round(time.monotonic() - start_time, 3)

            # Determine completion status
            if response is None:
                status = "no_iterations"
            elif iterations >= self.max_iterations and tool_calls:
                status = "max_iterations"
                logger.warning(
                    f"Agent reached max_iterations ({self.max_iterations}) with pending tool calls"
                )
            else:
                status = "completed"

            return ExecutionResult(
                output=response.text if response else None,
                status=status,
                metadata={
                    "iterations": iterations,
                    "model": self.model,
                    "tools_used": all_tools_used,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "duration_seconds": total_duration,
                    "iteration_stats": iteration_stats,
                },
                cost=total_cost,
                tokens_used=total_tokens,
            )

        except Exception as e:
            total_duration = round(time.monotonic() - start_time, 3)
            logger.error(f"Agent execution failed: {e}")
            return ExecutionResult(
                output=None,
                status="failed",
                metadata={
                    "error": str(e),
                    "iterations": iterations,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "duration_seconds": total_duration,
                    "iteration_stats": iteration_stats,
                },
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

    def execute(
        self,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None = None,
    ) -> ExecutionResult:
        """Execute without tool loop.

        Args:
            context: Execution context with data and configuration.
            on_chunk: Optional callback invoked with each text delta during streaming.
        """
        user_message = f"Goal: {context.goal}"
        if context.data:
            user_message += f"\n\nContext data:\n{json.dumps(context.data, indent=2, default=str)}"
        self.memory.add_user(user_message)

        try:
            llm = self._get_llm()
            gen_kwargs: dict[str, Any] = {
                "prompt": self.memory.get_messages(),
                "model": self.model,
                "temperature": self.temperature,
            }

            if on_chunk is not None:
                full_text = ""
                final_response = None
                for chunk in llm.generate_stream(**gen_kwargs):
                    if chunk.text:
                        on_chunk(chunk.text)
                        full_text += chunk.text
                    final_response = chunk

                if final_response is None:
                    response = LLMResponse(text="", model=self.model, tokens_used=0, cost=0.0)
                else:
                    response = final_response
                    response.text = full_text
            else:
                response = llm.generate(**gen_kwargs)

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
        output_schema: dict[str, Any],
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
