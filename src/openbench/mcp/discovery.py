"""Discovery data structures for MCP clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveredMCPServer:
    """Capabilities discovered from one MCP server."""

    name: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    prompts: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class MCPDiscoveryCache:
    """In-memory discovery cache."""

    servers: dict[str, DiscoveredMCPServer] = field(default_factory=dict)

    def list_namespaced_tools(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for server_name, server in self.servers.items():
            for tool_name, tool in server.tools.items():
                result[f"{server_name}.{tool_name}"] = tool
        return result

    def clear(self) -> None:
        self.servers.clear()
