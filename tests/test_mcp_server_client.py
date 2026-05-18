"""Tests for OpenBench MCP server/client wrappers without external MCP SDK."""

from __future__ import annotations

import asyncio

import pytest

from openbench.core.abstractions import Tool
from openbench.intelligence.base import ToolExecutor
from openbench.mcp.adapters import MCPToolAdapter
from openbench.mcp.client import MCPClient
from openbench.mcp.config import MCPClientConfig, MCPServerConfig, MCPServerConnectionConfig
from openbench.mcp.server import OpenBenchMCPServer
from openbench.mcp.transports import InMemoryMCPTransport, MCPTransport


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


@pytest.fixture()
def openbench_mcp_server() -> OpenBenchMCPServer:
    return OpenBenchMCPServer(MCPServerConfig(name="openbench", include_sdk_tools=True))


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
        approved=True,
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
        approved=True,
    )
    adapter.client.call_tool_sync = lambda *args, **kwargs: (_ for _ in ()).throw(
        ClosedResourceError()
    )

    with pytest.raises(RuntimeError, match="ClosedResourceError"):
        adapter.execute()
