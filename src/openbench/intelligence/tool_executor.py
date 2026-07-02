"""Unified tool execution for OpenBench agents.

Provides :class:`ToolExecutor` (sequential + parallel tool dispatch with
per-call timeout and ContextVar propagation) and the tool-result JSON
serialization helpers. Extracted from ``intelligence/base.py``; ``base`` still
re-exports these names for backward compatibility.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
import threading
from typing import TYPE_CHECKING, Any

from openbench.core.abstractions import Tool
from openbench.core.constants import DEFAULT_TOOL_TIMEOUT_S

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


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
            resolved_timeout = getattr(tool, "timeout_seconds", DEFAULT_TOOL_TIMEOUT_S)
        try:
            resolved_timeout = float(resolved_timeout)
        except (TypeError, ValueError):
            resolved_timeout = DEFAULT_TOOL_TIMEOUT_S

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

        # Time each tool dispatch through the shared MCP metrics sink.
        # Imported lazily to avoid an import cycle (mcp <-> intelligence).
        from openbench.mcp.observability import timed_operation

        with timed_operation("agent.tool_execute", tool=name):
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
