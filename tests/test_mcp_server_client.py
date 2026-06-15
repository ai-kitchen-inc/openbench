"""Tests for OpenBench MCP server/client wrappers without external MCP SDK."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from openbench.core.abstractions import Tool
from openbench.intelligence.base import ToolExecutor
import openbench.mcp.adapters as adapters_module
from openbench.mcp.adapters import MCPToolAdapter, load_mcp_tools
from openbench.mcp.client import MCPClient
from openbench.mcp.config import (
    MCPClientConfig,
    MCPPolicyConfig,
    MCPServerConfig,
    MCPServerConnectionConfig,
)
from openbench.mcp.errors import MCPPolicyDeniedError
from openbench.mcp.permissions import MCPPermissionSession
from openbench.mcp.server import OpenBenchMCPServer
from openbench.mcp.transports import InMemoryMCPTransport, MCPTransport, StreamableHTTPTransport


def approve_mcp(_request):
    return "yes"


class LoopBoundTransport(MCPTransport):
    def __init__(self):
        self.loop_ids: list[int] = []

    async def initialize(self) -> dict:
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return {"capabilities": {"tools": {}}}

    async def list_tools(self) -> list[dict]:
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return [
            {
                "name": "echo",
                "description": "Echo a value",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.loop_ids.append(id(asyncio.get_running_loop()))
        if len(set(self.loop_ids)) != 1:
            return {"isError": True, "content": [{"type": "text", "text": "loop changed"}]}
        return {"isError": False, "structuredContent": {"value": arguments["value"]}}


class ClosedResourceError(Exception):
    pass


class ReconnectableTransport(MCPTransport):
    instances: list[ReconnectableTransport] = []

    def __init__(self, *, fail_call: bool):
        self.fail_call = fail_call
        self.closed = False
        ReconnectableTransport.instances.append(self)

    async def initialize(self) -> dict:
        return {"capabilities": {"tools": {}}}

    async def list_tools(self) -> list[dict]:
        return [
            {
                "name": "echo",
                "description": "Echo a value",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if self.fail_call:
            raise ClosedResourceError()
        return {"isError": False, "structuredContent": {"value": arguments["value"]}}

    async def close(self) -> None:
        self.closed = True


class CloseTaskTrackingTransport(MCPTransport):
    def __init__(self):
        self.task_ids: list[int] = []
        self.closed = False

    def _record_task(self) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.task_ids.append(id(task))

    async def initialize(self) -> dict:
        self._record_task()
        return {"capabilities": {"tools": {}}}

    async def list_tools(self) -> list[dict]:
        self._record_task()
        return [
            {
                "name": "echo",
                "description": "Echo a value",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        ]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return {"isError": False, "structuredContent": arguments}

    async def close(self) -> None:
        self._record_task()
        self.closed = True


class SlowDiscoveryTransport(MCPTransport):
    def __init__(self, *, delay_seconds: float):
        self.delay_seconds = delay_seconds
        self.closed = False

    async def initialize(self) -> dict:
        await asyncio.sleep(self.delay_seconds)
        return {"capabilities": {"tools": {}}}

    async def list_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return {"isError": False, "structuredContent": arguments}

    async def close(self) -> None:
        self.closed = True


class FakeStreamableSession:
    instances: list[FakeStreamableSession] = []

    def __init__(self, read, write):
        self.read = read
        self.write = write
        self.closed = False
        self.calls: list[tuple[str, dict]] = []
        FakeStreamableSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True

    async def initialize(self):
        return {"capabilities": {"tools": {}}}

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                {
                    "name": "git_status",
                    "description": "Read git status",
                    "inputSchema": {"type": "object", "properties": {}, "required": []},
                }
            ]
        )

    async def list_resources(self):
        return SimpleNamespace(resources=[])

    async def list_prompts(self):
        return SimpleNamespace(prompts=[])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {
            "isError": False,
            "structuredContent": {"name": name, "arguments": arguments},
        }


@pytest.fixture()
def openbench_mcp_server() -> OpenBenchMCPServer:
    return OpenBenchMCPServer(MCPServerConfig(name="openbench", include_sdk_tools=True))


@pytest.fixture()
def fake_streamable_sdk(monkeypatch):
    FakeStreamableSession.instances = []
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_streamablehttp_client(
        url,
        headers=None,
        timeout=30,
        sse_read_timeout=300,
        **kwargs,
    ):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["sse_read_timeout"] = sse_read_timeout
        yield "read", "write", lambda: "session-1"

    monkeypatch.setattr("mcp.client.streamable_http.streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr("mcp.ClientSession", FakeStreamableSession)
    return captured


def test_server_exposes_sdk_tools_resources_and_prompts(openbench_mcp_server):
    tools = openbench_mcp_server.list_tools()
    tool_names = {tool["name"] for tool in tools}

    assert "filter_records" in tool_names
    assert "read_pdf" in tool_names
    assert "export_to_excel" in tool_names
    assert any(r["uri"].startswith("openbench://skills/") for r in openbench_mcp_server.list_resources())
    assert "summarize_pdf" in {p["name"] for p in openbench_mcp_server.list_prompts()}


def test_server_call_tool_preserves_structured_result(openbench_mcp_server):
    result = openbench_mcp_server.call_tool(
        "filter_records",
        {
            "records": [{"region": "EU", "amount": 1}, {"region": "US", "amount": 2}],
            "conditions": [{"column": "region", "op": "eq", "value": "EU"}],
        },
    )

    assert result["isError"] is False
    assert result["structuredContent"]["count"] == 1
    assert "EU" in result["content"][0]["text"]


def test_server_maps_openbench_error_dict_to_mcp_error(openbench_mcp_server):
    result = openbench_mcp_server.call_tool("top_n_records", {"records": [], "by": "x", "n": 0})

    assert result["isError"] is True
    assert "error" in result["structuredContent"]


def test_client_discovers_and_calls_namespaced_tool(openbench_mcp_server):
    client = MCPClient(transports={"openbench": InMemoryMCPTransport(openbench_mcp_server)})
    discovered = client.discover_sync()

    assert "filter_records" in discovered.servers["openbench"].tools
    result = client.call_tool_sync(
        "openbench.filter_records",
        {
            "records": [{"region": "EU"}, {"region": "US"}],
            "conditions": [{"column": "region", "value": "US"}],
        },
    )
    assert result["count"] == 1
    client.close_sync()


def test_client_sync_calls_reuse_one_event_loop():
    transport = LoopBoundTransport()
    client = MCPClient(transports={"loop": transport})

    discovered = client.discover_sync()
    result = client.call_tool_sync("loop.echo", {"value": "ok"})
    client.close_sync()

    assert "echo" in discovered.servers["loop"].tools
    assert result == {"value": "ok"}
    assert len(set(transport.loop_ids)) == 1


def test_client_discover_and_close_uses_one_task_for_short_lived_stdio_lifecycle():
    transport = CloseTaskTrackingTransport()
    client = MCPClient(transports={"loop": transport})

    discovered = client.discover_and_close_sync(refresh=True)

    assert "echo" in discovered.servers["loop"].tools
    assert transport.closed is True
    assert len(set(transport.task_ids)) == 1


def test_client_discovery_timeout_is_separate_from_tool_timeout(monkeypatch):
    slow_transport = SlowDiscoveryTransport(delay_seconds=0.1)

    monkeypatch.setattr("openbench.mcp.client.build_transport", lambda _config: slow_transport)
    client = MCPClient(
        MCPClientConfig(
            servers={
                "sam": MCPServerConnectionConfig(
                    command="fake-mcp",
                    namespace="sam",
                    allowed=True,
                    discovery_timeout_seconds=0.01,
                    timeout_seconds=3600,
                )
            }
        )
    )

    with pytest.raises(Exception, match="Timed out discovering MCP server 'sam' after 0.01s"):
        client.discover_sync()

    assert slow_transport.closed is True
    assert client._server_configs["sam"].timeout_seconds == 3600


def test_streamable_http_transport_uses_mcp_sdk_session(fake_streamable_sdk):
    transport = StreamableHTTPTransport(
        MCPServerConnectionConfig(
            transport="streamable-http",
            url="http://127.0.0.1:39670/mcp",
            headers={"X-Test": "yes"},
            timeout_seconds=12,
        )
    )

    capabilities = asyncio.run(transport.initialize())
    tools = asyncio.run(transport.list_tools())
    result = asyncio.run(transport.call_tool("git_status", {"repo": "."}))
    asyncio.run(transport.close())

    assert capabilities == {"capabilities": {"tools": {}}}
    assert tools[0]["name"] == "git_status"
    assert result["structuredContent"] == {"name": "git_status", "arguments": {"repo": "."}}
    assert fake_streamable_sdk["url"] == "http://127.0.0.1:39670/mcp"
    assert fake_streamable_sdk["headers"] == {"X-Test": "yes"}
    assert fake_streamable_sdk["timeout"] == 12
    assert fake_streamable_sdk["sse_read_timeout"] == 12
    assert FakeStreamableSession.instances[-1].closed is True


def test_streamable_http_client_discovers_toolhive_git_tools(fake_streamable_sdk):
    client = MCPClient(
        MCPClientConfig(
            servers={
                "git": MCPServerConnectionConfig(
                    transport="streamable-http",
                    url="http://127.0.0.1:39670/mcp",
                    namespace="git",
                    allowed=True,
                )
            }
        )
    )

    discovered = client.discover_and_close_sync(refresh=True)

    assert "git_status" in discovered.servers["git"].tools
    assert FakeStreamableSession.instances[-1].closed is True


def test_client_reconnects_stdio_once_after_closed_resource(monkeypatch):
    ReconnectableTransport.instances = []

    def build_fake_transport(config):
        return ReconnectableTransport(fail_call=len(ReconnectableTransport.instances) == 0)

    monkeypatch.setattr("openbench.mcp.client.build_transport", build_fake_transport)
    client = MCPClient(
        MCPClientConfig(
            servers={
                "files": MCPServerConnectionConfig(
                    command="fake-mcp",
                    namespace="files",
                    allowed=True,
                    retries=0,
                )
            }
        )
    )

    client.discover_sync()
    result = client.call_tool_sync("files.echo", {"value": "ok"})
    client.close_sync()

    assert result == {"value": "ok"}
    assert len(ReconnectableTransport.instances) == 2
    assert ReconnectableTransport.instances[0].closed is True


def test_client_reconnects_streamable_http_once_after_closed_resource(monkeypatch):
    ReconnectableTransport.instances = []

    def build_fake_transport(config):
        return ReconnectableTransport(fail_call=len(ReconnectableTransport.instances) == 0)

    monkeypatch.setattr("openbench.mcp.client.build_transport", build_fake_transport)
    client = MCPClient(
        MCPClientConfig(
            servers={
                "time": MCPServerConnectionConfig(
                    transport="streamable-http",
                    namespace="time",
                    url="http://127.0.0.1:59522/mcp",
                    allowed=True,
                    retries=0,
                )
            },
            policy=MCPPolicyConfig(allow_remote_servers=True),
        )
    )

    client.discover_sync()
    result = client.call_tool_sync("time.echo", {"value": "ok"})
    client.close_sync()

    assert result == {"value": "ok"}
    assert len(ReconnectableTransport.instances) == 2
    assert ReconnectableTransport.instances[0].closed is True


def test_client_close_after_call_closes_and_replaces_transport_after_success(monkeypatch):
    ReconnectableTransport.instances = []

    def build_fake_transport(config):
        return ReconnectableTransport(fail_call=False)

    monkeypatch.setattr("openbench.mcp.client.build_transport", build_fake_transport)
    client = MCPClient(
        MCPClientConfig(
            servers={
                "time": MCPServerConnectionConfig(
                    command="fake-mcp",
                    namespace="time",
                    allowed=True,
                )
            }
        )
    )

    first = client.call_tool_sync("time.echo", {"value": "one"}, close_after_call=True)
    second = client.call_tool_sync("time.echo", {"value": "two"}, close_after_call=True)
    client.close_sync()

    assert first == {"value": "one"}
    assert second == {"value": "two"}
    assert len(ReconnectableTransport.instances) == 3
    assert ReconnectableTransport.instances[0].closed is True
    assert ReconnectableTransport.instances[1].closed is True


def test_client_close_after_call_closes_and_replaces_transport_after_failure(monkeypatch):
    ReconnectableTransport.instances = []

    class BrokenTransport(ReconnectableTransport):
        async def call_tool(self, name: str, arguments: dict) -> dict:
            raise ValueError("server exploded")

    def build_fake_transport(config):
        return BrokenTransport(fail_call=False)

    monkeypatch.setattr("openbench.mcp.client.build_transport", build_fake_transport)
    client = MCPClient(
        MCPClientConfig(
            servers={
                "time": MCPServerConnectionConfig(
                    command="fake-mcp",
                    namespace="time",
                    allowed=True,
                    retries=0,
                )
            }
        )
    )

    try:
        with pytest.raises(ValueError, match="server exploded"):
            client.call_tool_sync("time.echo", {"value": "ok"}, close_after_call=True)
    finally:
        client.close_sync()

    assert len(ReconnectableTransport.instances) == 2
    assert ReconnectableTransport.instances[0].closed is True


def test_client_does_not_reconnect_streamable_http_for_non_closed_error(monkeypatch):
    ReconnectableTransport.instances = []

    class BrokenTransport(ReconnectableTransport):
        async def call_tool(self, name: str, arguments: dict) -> dict:
            raise ValueError("server exploded")

    def build_fake_transport(config):
        return BrokenTransport(fail_call=False)

    monkeypatch.setattr("openbench.mcp.client.build_transport", build_fake_transport)
    client = MCPClient(
        MCPClientConfig(
            servers={
                "time": MCPServerConnectionConfig(
                    transport="streamable-http",
                    namespace="time",
                    url="http://127.0.0.1:59522/mcp",
                    allowed=True,
                    retries=0,
                )
            },
            policy=MCPPolicyConfig(allow_remote_servers=True),
        )
    )

    client.discover_sync()
    try:
        with pytest.raises(ValueError, match="server exploded"):
            client.call_tool_sync("time.echo", {"value": "ok"})
    finally:
        client.close_sync()

    assert len(ReconnectableTransport.instances) == 1


def test_client_namespaces_prevent_collisions(openbench_mcp_server):
    client = MCPClient(
        transports={
            "a": InMemoryMCPTransport(openbench_mcp_server),
            "b": InMemoryMCPTransport(openbench_mcp_server),
        }
    )
    tools = client.discover_sync().list_namespaced_tools()

    assert "a.filter_records" in tools
    assert "b.filter_records" in tools


def test_mcp_tool_adapter_works_with_tool_executor(openbench_mcp_server):
    client = MCPClient(transports={"openbench": InMemoryMCPTransport(openbench_mcp_server)})
    client.discover_sync()
    schema = client.get_tool_schema("openbench.distinct_values")
    adapter = MCPToolAdapter(
        client=client,
        namespaced_name="openbench.distinct_values",
        tool_schema=schema,
        permission_provider=approve_mcp,
    )

    assert isinstance(adapter, Tool)
    executor = ToolExecutor()
    executor.register(adapter.name, adapter)
    result = executor.execute(
        adapter.name,
        records=[{"region": "EU"}, {"region": "US"}, {"region": "EU"}],
        column="region",
    )
    assert result["values"] == ["EU", "US"]
    provider_schema = adapter.get_schema()
    assert provider_schema["function"]["name"] == "openbench_distinct_values"


def test_mcp_tool_adapter_reports_empty_exception_class(openbench_mcp_server):
    client = MCPClient(transports={"openbench": InMemoryMCPTransport(openbench_mcp_server)})
    adapter = MCPToolAdapter(
        client=client,
        namespaced_name="openbench.distinct_values",
        tool_schema={
            "name": "distinct_values",
            "description": "Distinct values",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        permission_provider=approve_mcp,
    )
    adapter.client.call_tool_sync = lambda *args, **kwargs: (_ for _ in ()).throw(
        ClosedResourceError()
    )

    with pytest.raises(RuntimeError, match="ClosedResourceError"):
        adapter.execute()


def test_mcp_tool_adapter_passes_configured_timeout_to_client(openbench_mcp_server):
    client = MCPClient(transports={"openbench": InMemoryMCPTransport(openbench_mcp_server)})
    adapter = MCPToolAdapter(
        client=client,
        namespaced_name="openbench.distinct_values",
        tool_schema={
            "name": "distinct_values",
            "description": "Distinct values",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        permission_provider=approve_mcp,
        timeout_seconds=123.0,
    )
    seen = {}

    def fake_call_tool_sync(*args, **kwargs):
        seen["timeout_seconds"] = kwargs.get("timeout_seconds")
        seen["close_after_call"] = kwargs.get("close_after_call")
        return {"ok": True}

    adapter.client.call_tool_sync = fake_call_tool_sync

    assert adapter.execute() == {"ok": True}
    assert seen["timeout_seconds"] == 123.0
    assert seen["close_after_call"] is True


def test_mcp_tool_adapter_can_opt_out_of_close_after_execute(openbench_mcp_server):
    client = MCPClient(transports={"openbench": InMemoryMCPTransport(openbench_mcp_server)})
    adapter = MCPToolAdapter(
        client=client,
        namespaced_name="openbench.distinct_values",
        tool_schema={
            "name": "distinct_values",
            "description": "Distinct values",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        permission_provider=approve_mcp,
        close_after_execute=False,
    )
    seen = {}

    def fake_call_tool_sync(*args, **kwargs):
        seen["close_after_call"] = kwargs.get("close_after_call")
        return {"ok": True}

    adapter.client.call_tool_sync = fake_call_tool_sync

    assert adapter.execute() == {"ok": True}
    assert seen["close_after_call"] is False


def test_mcp_tool_adapter_approved_permission_calls_client():
    seen = {}

    class FakeClient:
        def call_tool_sync(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return {"ok": True}

    adapter = MCPToolAdapter(
        client=FakeClient(),
        namespaced_name="openbench.distinct_values",
        tool_schema={"description": "Distinct values"},
        permission_provider=lambda request: "approve",
    )

    assert adapter.execute(column="region") == {"ok": True}
    assert seen["args"] == ("openbench.distinct_values", {"column": "region"})
    assert seen["kwargs"]["approved"] is True


def test_mcp_tool_adapter_denied_permission_blocks_client():
    class FakeClient:
        def call_tool_sync(self, *args, **kwargs):
            raise AssertionError("MCP client should not be called")

    adapter = MCPToolAdapter(
        client=FakeClient(),
        namespaced_name="openbench.distinct_values",
        tool_schema={"description": "Distinct values"},
        permission_provider=lambda request: "no",
    )

    with pytest.raises(MCPPolicyDeniedError, match="not approved"):
        adapter.execute(column="region")


def test_mcp_tool_adapter_ambiguous_permission_blocks_client():
    class FakeClient:
        def call_tool_sync(self, *args, **kwargs):
            raise AssertionError("MCP client should not be called")

    adapter = MCPToolAdapter(
        client=FakeClient(),
        namespaced_name="openbench.distinct_values",
        tool_schema={"description": "Distinct values"},
        permission_provider=lambda request: "maybe",
    )

    with pytest.raises(MCPPolicyDeniedError, match="not approved"):
        adapter.execute(column="region")


def test_mcp_tool_adapter_missing_permission_provider_blocks_client():
    class FakeClient:
        def call_tool_sync(self, *args, **kwargs):
            raise AssertionError("MCP client should not be called")

    adapter = MCPToolAdapter(
        client=FakeClient(),
        namespaced_name="openbench.distinct_values",
        tool_schema={"description": "Distinct values"},
    )

    with pytest.raises(MCPPolicyDeniedError, match="not approved"):
        adapter.execute(column="region")


def test_mcp_tool_adapter_reuses_cached_permission_for_same_action():
    prompts = []
    calls = []

    class FakeClient:
        def call_tool_sync(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"ok": True}

    def provider(request):
        prompts.append(request)
        return "yes"

    adapter = MCPToolAdapter(
        client=FakeClient(),
        namespaced_name="openbench.distinct_values",
        tool_schema={"description": "Distinct values"},
        permission_session=MCPPermissionSession(provider),
    )

    adapter.execute(column="region")
    adapter.execute(column="region")

    assert len(prompts) == 1
    assert len(calls) == 2


def test_mcp_tool_adapter_prompts_again_when_action_changes():
    prompts = []

    class FakeClient:
        def call_tool_sync(self, *args, **kwargs):
            return {"ok": True}

    def provider(request):
        prompts.append(request)
        return "yes"

    adapter = MCPToolAdapter(
        client=FakeClient(),
        namespaced_name="openbench.distinct_values",
        tool_schema={"description": "Distinct values"},
        permission_session=MCPPermissionSession(provider),
    )

    adapter.execute(column="region")
    adapter.execute(column="country")

    assert len(prompts) == 2


def test_load_mcp_tools_propagates_server_timeout(monkeypatch):
    schema = {
        "name": "count_objects_with_sam3",
        "description": "Count concept instances",
        "inputSchema": {
            "type": "object",
            "properties": {"concept": {"type": "string"}},
            "required": ["concept"],
        },
    }

    class FakeMCPClient:
        def __init__(self, config):
            self.config = config

        def discover_sync(self):
            return SimpleNamespace(
                servers={
                    "sam_segmentation": SimpleNamespace(
                        tools={"count_objects_with_sam3": schema}
                    )
                }
            )

    monkeypatch.setattr(adapters_module, "MCPClient", FakeMCPClient)
    config = MCPClientConfig(
        servers={
            "sam": MCPServerConnectionConfig(
                command="noop",
                namespace="sam_segmentation",
                timeout_seconds=456.0,
            )
        }
    )

    tools = load_mcp_tools(config)

    assert len(tools) == 1
    assert tools[0].namespaced_name == "sam_segmentation.count_objects_with_sam3"
    assert tools[0].timeout_seconds == 456.0
