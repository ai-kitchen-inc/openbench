"""Adapters that expose MCP tools through OpenBench's Tool abstraction."""

from __future__ import annotations

from typing import Any

from openbench.core.abstractions import Tool
from openbench.mcp.client import MCPClient
from openbench.mcp.config import MCPClientConfig, MCPConfig
from openbench.mcp.schema import mcp_tool_to_openai_schema, provider_safe_tool_name


class MCPToolAdapter(Tool):
    """An MCP tool that can be registered with ``BaseAgent``."""

    def __init__(
        self,
        *,
        client: MCPClient,
        namespaced_name: str,
        tool_schema: dict[str, Any],
        approved: bool = False,
        timeout_seconds: float | None = None,
    ):
        self.client = client
        self.namespaced_name = namespaced_name
        self.tool_schema = tool_schema
        self.approved = approved
        self.timeout_seconds = timeout_seconds
        self._provider_name = provider_safe_tool_name(namespaced_name)

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def description(self) -> str:
        desc = self.tool_schema.get("description", "")
        return f"{desc}\n\nMCP tool: {self.namespaced_name}".strip()

    def execute(self, **params: Any) -> Any:
        try:
            return self.client.call_tool_sync(
                self.namespaced_name,
                params,
                timeout_seconds=self.timeout_seconds,
                approved=self.approved,
            )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            raise RuntimeError(f"{self.namespaced_name} failed: {message}") from exc

    def get_schema(self) -> dict[str, Any]:
        schema = mcp_tool_to_openai_schema(
            self.tool_schema,
            namespaced_name=self.namespaced_name,
        )
        schema["function"]["name"] = self.name
        schema["function"]["description"] = self.description
        return schema


def load_mcp_tools(config: MCPConfig | MCPClientConfig) -> list[MCPToolAdapter]:
    """Discover configured MCP servers and return Tool adapters."""
    client_config = config.client_config() if isinstance(config, MCPConfig) else config
    client = MCPClient(client_config)
    discovered = client.discover_sync()
    tools: list[MCPToolAdapter] = []
    configs_by_namespace = {
        server_config.namespace or server_name: server_config
        for server_name, server_config in client_config.servers.items()
    }
    for server_name, server in discovered.servers.items():
        server_config = configs_by_namespace.get(server_name)
        for tool_name, tool_schema in server.tools.items():
            namespaced = f"{server_name}.{tool_name}"
            tools.append(
                MCPToolAdapter(
                    client=client,
                    namespaced_name=namespaced,
                    tool_schema=tool_schema,
                    timeout_seconds=server_config.timeout_seconds
                    if server_config is not None
                    else None,
                )
            )
    return tools
