"""MCP client transports."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from openbench.mcp.errors import MCPTransportError

if TYPE_CHECKING:
    from openbench.mcp.config import MCPServerConnectionConfig


class MCPTransport(ABC):
    """Minimal transport protocol used by :class:`MCPClient`."""

    @abstractmethod
    async def initialize(self) -> dict[str, Any]:
        """Initialize a session."""

    @abstractmethod
    async def list_tools(self) -> list[dict[str, Any]]:
        """List tools."""

    async def list_resources(self) -> list[dict[str, Any]]:
        return []

    async def list_prompts(self) -> list[dict[str, Any]]:
        return []

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool."""

    async def close(self) -> None:
        """Close transport resources."""
        return None


class InMemoryMCPTransport(MCPTransport):
    """Test/local transport backed by an :class:`OpenBenchMCPServer` instance."""

    def __init__(self, server: Any):
        self.server = server

    async def initialize(self) -> dict[str, Any]:
        return {"capabilities": {"tools": {}, "resources": {}, "prompts": {}}}

    async def list_tools(self) -> list[dict[str, Any]]:
        return self.server.list_tools()

    async def list_resources(self) -> list[dict[str, Any]]:
        return self.server.list_resources()

    async def list_prompts(self) -> list[dict[str, Any]]:
        return self.server.list_prompts()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.server.call_tool(name, arguments, approved=True)


class StreamableHTTPTransport(MCPTransport):
    """MCP Streamable HTTP transport using the official MCP Python SDK."""

    def __init__(self, config: MCPServerConnectionConfig):
        self.config = config
        self._exit_stack: Any = None
        self._session: Any = None

    async def _ensure_session(self) -> Any:
        if self._session is None:
            try:
                from contextlib import AsyncExitStack

                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client
            except ImportError as exc:
                raise ImportError("MCP SDK is required for Streamable HTTP MCP") from exc

            self._exit_stack = AsyncExitStack()
            read, write, _get_session_id = await self._exit_stack.enter_async_context(
                streamablehttp_client(
                    self.config.url,
                    headers=self.config.headers or None,
                    timeout=self.config.timeout_seconds,
                    sse_read_timeout=self.config.timeout_seconds,
                )
            )
            self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        return self._session

    async def initialize(self) -> dict[str, Any]:
        session = await self._ensure_session()
        result = await session.initialize()
        return _model_to_dict(result)

    async def list_tools(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        result = await session.list_tools()
        return [_model_to_dict(tool) for tool in result.tools]

    async def list_resources(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        result = await session.list_resources()
        return [_model_to_dict(resource) for resource in result.resources]

    async def list_prompts(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        result = await session.list_prompts()
        return [_model_to_dict(prompt) for prompt in result.prompts]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session = await self._ensure_session()
        result = await session.call_tool(name, arguments)
        return _model_to_dict(result)

    async def close(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except RuntimeError as exc:
                if "Attempted to exit cancel scope in a different task" not in str(exc):
                    raise
            self._exit_stack = None
            self._session = None


class StdioMCPTransport(MCPTransport):
    """MCP stdio transport using the optional MCP Python SDK."""

    def __init__(self, config: MCPServerConnectionConfig):
        self.config = config
        self._exit_stack: Any = None
        self._session: Any = None

    async def initialize(self) -> dict[str, Any]:
        try:
            from contextlib import AsyncExitStack

            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise ImportError("MCP SDK is required for stdio MCP transport") from exc

        self._exit_stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
            cwd=self.config.cwd,
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        result = await self._session.initialize()
        return _model_to_dict(result)

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._session.list_tools()
        return [_model_to_dict(tool) for tool in result.tools]

    async def list_resources(self) -> list[dict[str, Any]]:
        result = await self._session.list_resources()
        return [_model_to_dict(resource) for resource in result.resources]

    async def list_prompts(self) -> list[dict[str, Any]]:
        result = await self._session.list_prompts()
        return [_model_to_dict(prompt) for prompt in result.prompts]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(name, arguments)
        return _model_to_dict(result)

    async def close(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except RuntimeError as exc:
                if "Attempted to exit cancel scope in a different task" not in str(exc):
                    raise
            self._exit_stack = None
            self._session = None


def build_transport(config: MCPServerConnectionConfig) -> MCPTransport:
    if config.transport == "stdio":
        return StdioMCPTransport(config)
    if config.transport == "streamable-http":
        return StreamableHTTPTransport(config)
    if config.transport == "sse":
        raise MCPTransportError(
            "SSE MCP transport is not yet supported by OpenBench. "
            "Use a ToolHive Streamable HTTP URL ending in /mcp."
        )
    raise MCPTransportError(f"Unsupported MCP transport: {config.transport}")


def _model_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {"result": value}


async def gather_with_concurrency(limit: int, *coros: Any) -> list[Any]:
    semaphore = asyncio.Semaphore(limit)

    async def run(coro: Any) -> Any:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(coro) for coro in coros))
