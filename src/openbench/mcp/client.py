"""Multi-server MCP client for OpenBench."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from contextlib import suppress
from typing import Any

from openbench.mcp.config import MCPClientConfig, MCPServerConnectionConfig
from openbench.mcp.discovery import DiscoveredMCPServer, MCPDiscoveryCache
from openbench.mcp.errors import (
    MCPCapabilityError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
    MCPTransportError,
)
from openbench.mcp.observability import correlation_context, get_correlation_id, metrics
from openbench.mcp.policy import MCPPolicyEngine
from openbench.mcp.schema import namespaced_tool_name, split_namespaced_tool
from openbench.mcp.transports import MCPTransport, build_transport, gather_with_concurrency


class MCPClient:
    """Discover and call tools across multiple MCP servers."""

    def __init__(
        self,
        config: MCPClientConfig | None = None,
        *,
        transports: dict[str, MCPTransport] | None = None,
        policy: MCPPolicyEngine | None = None,
    ):
        self.config = config or MCPClientConfig()
        self._transports: dict[str, MCPTransport] = {}
        self._server_configs: dict[str, MCPServerConnectionConfig] = {}
        for name, server_config in self.config.servers.items():
            if not server_config.enabled:
                continue
            namespace = server_config.namespace or name
            self._server_configs[namespace] = server_config
            if transports and namespace in transports:
                self._transports[namespace] = transports[namespace]
            else:
                self._transports[namespace] = build_transport(server_config)
        if transports:
            for name, transport in transports.items():
                self._transports.setdefault(name, transport)
                self._server_configs.setdefault(name, MCPServerConnectionConfig(command="noop"))

        allowed_servers = set(self.config.policy.allowed_servers)
        allowed_servers.update(
            name for name, cfg in self._server_configs.items() if cfg.allowed or cfg.transport == "stdio"
        )
        self.policy = policy or MCPPolicyEngine(
            allowed_servers=sorted(allowed_servers),
            denied_servers=self.config.policy.denied_servers,
            allowed_tools=self.config.policy.allowed_tools,
            denied_tools=self.config.policy.denied_tools,
            require_approval_for_risks=[
                str(risk) for risk in self.config.policy.require_approval_for_risks
            ],
            allow_remote_servers=self.config.policy.allow_remote_servers,
            max_timeout_seconds=self.config.policy.max_timeout_seconds,
            max_response_chars=self.config.policy.max_response_chars,
        )
        self.discovery = MCPDiscoveryCache()
        self._sync_runner = _MCPClientSyncRunner()

    async def discover(self, *, refresh: bool = False) -> MCPDiscoveryCache:
        """Initialize all servers and refresh discovery cache."""
        if self.discovery.servers and not refresh:
            return self.discovery
        if refresh:
            self.discovery.clear()

        coros = [self._discover_server(name, transport) for name, transport in self._transports.items()]
        results = await gather_with_concurrency(self.config.policy.max_concurrency, *coros)
        for server in results:
            self.discovery.servers[server.name] = server
        return self.discovery

    def discover_sync(self, *, refresh: bool = False) -> MCPDiscoveryCache:
        return self._run_sync(self.discover(refresh=refresh))

    async def discover_and_close(self, *, refresh: bool = False) -> MCPDiscoveryCache:
        """Discover tools for short-lived clients and close in the same task.

        The MCP Python SDK's stdio transport uses AnyIO cancel scopes that
        must be closed from the task that opened them. This helper avoids the
        cross-task close path used by concurrent discovery, which is especially
        noisy on Windows/Python 3.13 for one-shot registry discovery.
        """
        if self.discovery.servers and not refresh:
            return self.discovery
        if refresh:
            self.discovery.clear()
        try:
            for name, transport in self._transports.items():
                self.discovery.servers[name] = await self._discover_server(name, transport)
            return self.discovery
        finally:
            for transport in self._transports.values():
                await transport.close()

    def discover_and_close_sync(self, *, refresh: bool = False) -> MCPDiscoveryCache:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run_sync_in_new_thread(self.discover_and_close(refresh=refresh))

        return _run_sync_in_new_thread(self.discover_and_close(refresh=refresh))

    async def _discover_server(self, name: str, transport: MCPTransport) -> DiscoveredMCPServer:
        with correlation_context():
            try:
                capabilities = await transport.initialize()
                tools = {
                    str(tool["name"]): tool
                    for tool in await transport.list_tools()
                    if isinstance(tool, dict) and "name" in tool
                }
                resources: dict[str, dict[str, Any]] = {}
                prompts: dict[str, dict[str, Any]] = {}
                try:
                    resources = {
                        str(resource["uri"]): resource
                        for resource in await transport.list_resources()
                        if isinstance(resource, dict) and "uri" in resource
                    }
                except Exception:
                    resources = {}
                try:
                    prompts = {
                        str(prompt["name"]): prompt
                        for prompt in await transport.list_prompts()
                        if isinstance(prompt, dict) and "name" in prompt
                    }
                except Exception:
                    prompts = {}
                return DiscoveredMCPServer(
                    name=name,
                    capabilities=capabilities,
                    tools=tools,
                    resources=resources,
                    prompts=prompts,
                )
            except Exception as exc:
                raise MCPTransportError(
                    f"Failed to discover MCP server {name!r}: {exc}",
                    server=name,
                    correlation_id=get_correlation_id(),
                    cause=exc,
                ) from exc

    def list_tools(self) -> dict[str, dict[str, Any]]:
        """Return all discovered tools keyed by namespaced name."""
        if not self.discovery.servers:
            self.discover_sync()
        return self.discovery.list_namespaced_tools()

    async def call_tool(
        self,
        namespaced_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
        approved: bool = False,
    ) -> Any:
        """Call a namespaced MCP tool."""
        server, tool = split_namespaced_tool(namespaced_name)
        if server not in self._transports:
            raise MCPToolNotFoundError(f"MCP server not configured: {server}", server=server)
        if not self.discovery.servers:
            await self.discover()
        discovered = self.discovery.servers.get(server)
        if discovered is None or tool not in discovered.tools:
            raise MCPToolNotFoundError(
                f"MCP tool not found: {namespaced_name}",
                server=server,
                tool=tool,
                correlation_id=get_correlation_id(),
            )

        cfg = self._server_configs[server]
        timeout = timeout_seconds or cfg.timeout_seconds
        self.policy.enforce(
            server=server,
            tool=tool,
            remote=cfg.transport != "stdio",
            approved=approved,
            timeout_seconds=timeout,
        )

        attempts = cfg.retries + 1
        last_error: BaseException | None = None
        reconnected = False
        for attempt in range(attempts):
            try:
                metrics.inc("tool_calls_total")
                return await asyncio.wait_for(
                    self._call_once(server, tool, arguments or {}, attempt),
                    timeout=timeout,
                )
            except MCPTransportError as exc:
                last_error = exc
                if self._should_reconnect_closed_session(cfg, exc, reconnected):
                    await self._reconnect_server(server)
                    reconnected = True
                    metrics.inc("tool_retries_total")
                    return await asyncio.wait_for(
                        self._call_once(server, tool, arguments or {}, attempt + 1),
                        timeout=timeout,
                    )
                if attempt >= attempts - 1:
                    break
                metrics.inc("tool_retries_total")
                await asyncio.sleep(cfg.retry_backoff_seconds * (attempt + 1))
            except TimeoutError as exc:
                last_error = exc
                break
            except Exception as exc:
                last_error = exc
                if self._should_reconnect_closed_session(cfg, exc, reconnected):
                    await self._reconnect_server(server)
                    reconnected = True
                    metrics.inc("tool_retries_total")
                    return await asyncio.wait_for(
                        self._call_once(server, tool, arguments or {}, attempt + 1),
                        timeout=timeout,
                    )
                raise
        raise MCPTransportError(
            f"MCP tool call failed after {attempts} attempt(s): {last_error}",
            server=server,
            tool=tool,
            correlation_id=get_correlation_id(),
            retry_count=max(0, attempts - 1),
            cause=last_error,
        )

    def call_tool_sync(
        self,
        namespaced_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
        approved: bool = False,
    ) -> Any:
        return self._run_sync(
            self.call_tool(
                namespaced_name,
                arguments,
                timeout_seconds=timeout_seconds,
                approved=approved,
            )
        )

    async def _call_once(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any],
        retry_count: int,
    ) -> Any:
        started = time.perf_counter()
        result = await self._transports[server].call_tool(tool, arguments)
        duration_ms = (time.perf_counter() - started) * 1000
        metrics.observe_ms("tool_latency_ms", duration_ms)
        if result.get("isError"):
            metrics.inc("tool_failures_total")
            message = _result_text(result) or f"MCP tool returned an error: {server}.{tool}"
            raise MCPToolExecutionError(
                message,
                server=server,
                tool=tool,
                correlation_id=get_correlation_id(),
                retry_count=retry_count,
                data={"result": result},
            )
        return result.get("structuredContent", result)

    async def _reconnect_server(self, server: str) -> None:
        stale_transport = self._transports[server]
        with suppress(Exception):
            await stale_transport.close()
        transport = build_transport(self._server_configs[server])
        self._transports[server] = transport
        self.discovery.servers[server] = await self._discover_server(server, transport)

    @staticmethod
    def _should_reconnect_closed_session(
        config: MCPServerConnectionConfig,
        exc: BaseException,
        already_reconnected: bool,
    ) -> bool:
        if already_reconnected or config.transport not in {"stdio", "streamable-http"}:
            return False
        return _is_closed_session_error(exc)

    async def close(self) -> None:
        await asyncio.gather(*(transport.close() for transport in self._transports.values()))

    def close_sync(self) -> None:
        self._run_sync(self.close())
        self._sync_runner.close()

    def get_tool_schema(self, namespaced_name: str) -> dict[str, Any]:
        if not self.discovery.servers:
            self.discover_sync()
        server, tool_name = split_namespaced_tool(namespaced_name)
        server_info = self.discovery.servers.get(server)
        if server_info is None:
            raise MCPCapabilityError(f"Server not discovered: {server}", server=server)
        tool = server_info.tools.get(tool_name)
        if tool is None:
            raise MCPToolNotFoundError(
                f"Tool not discovered: {namespaced_name}", server=server, tool=tool_name
            )
        return tool

    def _run_sync(self, coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._sync_runner.run(coro)

        return _run_sync_in_new_thread(coro)


def _result_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return str(first.get("text") or "")
    return ""


def _is_closed_session_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = current.__class__.__name__
        message = str(current)
        if name == "ClosedResourceError" or "Connection closed" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


class _MCPClientSyncRunner:
    """Run sync MCP calls on one persistent event loop.

    Stdio MCP sessions are tied to the loop that opened their streams. Keeping
    all sync discovery and tool calls on the same loop lets a discovered stdio
    server remain usable for later ``Tool.execute()`` calls.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._lock = threading.Lock()

    def run(self, coro: Any) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def close(self) -> None:
        with self._lock:
            if self._loop is None:
                return
            loop = self._loop
            thread = self._thread
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(timeout=5)
            self._loop = None
            self._thread = None
            self._started.clear()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            self._started.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="openbench-mcp-client",
                daemon=True,
            )
            self._thread.start()
            self._started.wait()
            if self._loop is None:
                raise RuntimeError("Failed to start MCP client event loop")
            return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._started.set()
        try:
            loop.run_forever()
        finally:
            loop.close()


def _run_sync_in_new_thread(coro: Any) -> Any:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def create_single_server_client(name: str, transport: MCPTransport) -> MCPClient:
    """Build a client around an already-constructed transport."""
    normalized = namespaced_tool_name(name, "noop").split(".", 1)[0]
    return MCPClient(transports={normalized: transport})
