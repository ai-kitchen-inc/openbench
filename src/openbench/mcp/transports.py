"""MCP client transports."""

from __future__ import annotations

import asyncio
import json
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
    """Small JSON-RPC Streamable HTTP MCP transport."""

    def __init__(self, config: MCPServerConnectionConfig):
        self.config = config
        self._client: Any = None
        self._request_id = 0
        self._session_id: str | None = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise ImportError("httpx is required for Streamable HTTP MCP") from exc
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        return self._client

    async def initialize(self) -> dict[str, Any]:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "openbench", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list", {})
        return list(result.get("tools", []))

    async def list_resources(self) -> list[dict[str, Any]]:
        result = await self._request("resources/list", {})
        return list(result.get("resources", []))

    async def list_prompts(self) -> list[dict[str, Any]]:
        result = await self._request("prompts/list", {})
        return list(result.get("prompts", []))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._request("tools/call", {"name": name, "arguments": arguments})

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        response = await self._post(payload)
        if response.status_code == 202 or not response.content:
            return {}
        data = response.json()
        if "error" in data:
            err = data["error"]
            raise MCPTransportError(str(err.get("message", err)), data=err)
        return dict(data.get("result") or {})

    async def _post(self, payload: dict[str, Any]) -> Any:
        client = await self._ensure_client()
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = await client.post(self.config.url, headers=headers, content=json.dumps(payload))
        if "Mcp-Session-Id" in response.headers:
            self._session_id = response.headers["Mcp-Session-Id"]
        response.raise_for_status()
        return response

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


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
    if config.transport in {"streamable-http", "sse"}:
        return StreamableHTTPTransport(config)
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
