"""Adapters that expose MCP tools through OpenBench's Tool abstraction."""

from __future__ import annotations

import json
from typing import Any

from openbench.core.abstractions import Tool
from openbench.mcp.client import MCPClient
from openbench.mcp.config import MCPClientConfig, MCPConfig
from openbench.mcp.errors import MCPPolicyDeniedError
from openbench.mcp.permissions import (
    MCPPermissionRequest,
    MCPPermissionSession,
    PermissionProvider,
    redacted_arguments,
)
from openbench.mcp.policy import classify_tool_risk
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
        permission_provider: PermissionProvider | None = None,
        permission_session: MCPPermissionSession | None = None,
        timeout_seconds: float | None = None,
        close_after_execute: bool = True,
    ):
        self.client = client
        self.namespaced_name = namespaced_name
        self.tool_schema = tool_schema
        self.approved = approved
        self.permission_session = permission_session or MCPPermissionSession(
            permission_provider
        )
        self.timeout_seconds = timeout_seconds
        self.close_after_execute = close_after_execute
        self._provider_name = provider_safe_tool_name(namespaced_name)

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def description(self) -> str:
        desc = self.tool_schema.get("description", "")
        return f"{desc}\n\nMCP tool: {self.namespaced_name}".strip()

    def execute(self, **params: Any) -> Any:
        permission = self._request_permission(params)
        if not permission.approved:
            server, _, tool = self.namespaced_name.partition(".")
            reason = permission.reason or "MCP tool use was not explicitly approved"
            raise MCPPolicyDeniedError(
                f"MCP tool {self.namespaced_name!r} was not approved: {reason}",
                server=server or None,
                tool=tool or self.namespaced_name,
                data={
                    "approval_required": True,
                    "permission_status": permission.status,
                    "raw_response": permission.raw_response,
                },
            )
        try:
            return self.client.call_tool_sync(
                self.namespaced_name,
                params,
                timeout_seconds=self.timeout_seconds,
                approved=True,
                close_after_call=self.close_after_execute,
            )
        except MCPPolicyDeniedError:
            raise
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            raise RuntimeError(f"{self.namespaced_name} failed: {message}") from exc

    def _request_permission(self, params: dict[str, Any]):
        redacted = redacted_arguments(params)
        risk = classify_tool_risk(self.namespaced_name)
        request = MCPPermissionRequest(
            tool_name=self.namespaced_name,
            purpose=str(self.tool_schema.get("description") or self.description),
            arguments=redacted,
            risk=risk,
            action=self._summarize_action(redacted),
        )
        return self.permission_session.request(request)

    def _summarize_action(self, arguments: dict[str, Any]) -> str:
        if not arguments:
            return f"Call MCP tool '{self.namespaced_name}' with no arguments."
        rendered = json.dumps(arguments, sort_keys=True, default=str)
        if len(rendered) > 500:
            rendered = f"{rendered[:497]}..."
        return f"Call MCP tool '{self.namespaced_name}' with arguments {rendered}."

    def get_schema(self) -> dict[str, Any]:
        schema = mcp_tool_to_openai_schema(
            self.tool_schema,
            namespaced_name=self.namespaced_name,
        )
        schema["function"]["name"] = self.name
        schema["function"]["description"] = self.description
        return schema


def load_mcp_tools(
    config: MCPConfig | MCPClientConfig,
    *,
    permission_provider: PermissionProvider | None = None,
    permission_session: MCPPermissionSession | None = None,
) -> list[MCPToolAdapter]:
    """Discover configured MCP servers and return Tool adapters."""
    client_config = config.client_config() if isinstance(config, MCPConfig) else config
    client = MCPClient(client_config)
    discovered = client.discover_sync()
    tools: list[MCPToolAdapter] = []
    shared_permission_session = permission_session or MCPPermissionSession(
        permission_provider
    )
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
                    permission_session=shared_permission_session,
                    timeout_seconds=server_config.timeout_seconds
                    if server_config is not None
                    else None,
                )
            )
    return tools
