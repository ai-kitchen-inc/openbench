"""OpenBench MCP server wrapper."""

from __future__ import annotations

import inspect
from typing import Any

from openbench.mcp.config import MCPServerConfig
from openbench.mcp.observability import get_correlation_id, metrics, timed_operation
from openbench.mcp.policy import MCPPolicyEngine
from openbench.mcp.prompts import DEFAULT_PROMPTS, MCPPrompt
from openbench.mcp.resources import MCPResource, resources_from_skills
from openbench.mcp.schema import is_error_result, sanitize_json_value, tool_result_to_text
from openbench.mcp.tool_registry import (
    OpenBenchMCPTool,
    build_skill_registry,
    collect_mcp_tools,
    loaded_skills,
)


class OpenBenchMCPServer:
    """Expose OpenBench skill tools through MCP."""

    def __init__(
        self,
        config: MCPServerConfig | None = None,
        *,
        policy: MCPPolicyEngine | None = None,
        runtime_bindings: dict[str, Any] | None = None,
    ):
        self.config = config or MCPServerConfig()
        self.policy = policy or MCPPolicyEngine(
            allowed_servers=self.config.policy.allowed_servers or [self.config.name],
            denied_servers=self.config.policy.denied_servers,
            allowed_tools=self.config.policy.allowed_tools,
            denied_tools=self.config.policy.denied_tools,
            require_approval_for_risks=[
                str(risk) for risk in self.config.policy.require_approval_for_risks
            ],
            allow_remote_servers=True,
            max_timeout_seconds=self.config.policy.max_timeout_seconds,
            max_response_chars=self.config.policy.max_response_chars,
        )
        self.registry = build_skill_registry(
            include_sdk_tools=self.config.include_sdk_tools,
            skills=self.config.skills,
        )
        if runtime_bindings:
            self.registry.bind(**runtime_bindings)
        self.skills = loaded_skills(self.registry)
        self.tools = collect_mcp_tools(self.registry)
        self._tool_map = {tool.name: tool for tool in self.tools}
        self.resources: dict[str, MCPResource] = resources_from_skills(self.skills)
        self.prompts: dict[str, MCPPrompt] = dict(DEFAULT_PROMPTS)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions."""
        return [tool.mcp_tool for tool in self.tools]

    def list_resources(self) -> list[dict[str, Any]]:
        """Return MCP resource definitions."""
        return [resource.to_mcp_dict() for resource in self.resources.values()]

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a static OpenBench resource."""
        resource = self.resources[uri]
        return {
            "contents": [
                {
                    "uri": resource.uri,
                    "mimeType": resource.mime_type,
                    "text": resource.text,
                }
            ]
        }

    def list_prompts(self) -> list[dict[str, Any]]:
        """Return MCP prompt definitions."""
        return [prompt.to_mcp_dict() for prompt in self.prompts.values()]

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render a reusable OpenBench prompt."""
        prompt = self.prompts[name]
        text = prompt.render(**(arguments or {}))
        return {
            "description": prompt.description,
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Call an OpenBench function tool and return an MCP-style result."""
        if name not in self._tool_map:
            return self._mcp_result({"error": f"Tool not found: {name}"}, is_error=True)
        tool = self._tool_map[name]
        decision = self.policy.authorize(
            server=self.config.name,
            tool=name,
            risk=tool.risk,
            approved=approved,
        )
        if not decision.allowed:
            return self._mcp_result(
                {
                    "error": decision.reason,
                    "approval_required": decision.approval_required,
                    "risk": decision.risk.value,
                    "correlation_id": get_correlation_id(),
                },
                is_error=True,
            )

        metrics.inc("tool_calls_total")
        try:
            with timed_operation(
                "tool_latency_ms",
                server=self.config.name,
                tool=name,
                transport="server",
                policy_decision="allowed",
            ):
                result = self._invoke(tool, arguments or {})
        except Exception as exc:
            metrics.inc("tool_failures_total")
            return self._mcp_result(
                {
                    "error": str(exc),
                    "correlation_id": get_correlation_id(),
                    "type": type(exc).__name__,
                },
                is_error=True,
            )
        return self._mcp_result(result, is_error=is_error_result(result))

    @staticmethod
    def _invoke(tool: OpenBenchMCPTool, arguments: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(tool.callable):
            raise TypeError("Async OpenBench skill callables are not supported yet")
        return tool.callable(**arguments)

    @staticmethod
    def _mcp_result(result: Any, *, is_error: bool = False) -> dict[str, Any]:
        structured = sanitize_json_value(result)
        return {
            "content": [{"type": "text", "text": tool_result_to_text(structured)}],
            "structuredContent": structured if isinstance(structured, dict) else {"result": structured},
            "isError": is_error,
        }

    def build_fastmcp(self) -> Any:
        """Build a FastMCP server instance.

        Raises:
            ImportError: If the optional MCP SDK is not installed.
        """
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError as exc:
            raise ImportError(
                "MCP SDK is required. Install with: pip install openbench[mcp]"
            ) from exc

        app = FastMCP(self.config.name, json_response=True)

        for tool in self.tools:
            self._register_fastmcp_tool(app, tool)
        for resource in self.resources.values():
            self._register_fastmcp_resource(app, resource)
        for prompt in self.prompts.values():
            self._register_fastmcp_prompt(app, prompt)
        return app

    def _register_fastmcp_tool(self, app: Any, tool: OpenBenchMCPTool) -> None:
        mcp_tool = tool.mcp_tool

        def wrapper(**kwargs: Any) -> Any:
            result = self.call_tool(tool.name, kwargs)
            try:
                from mcp.types import CallToolResult, TextContent
            except Exception:
                return result
            return CallToolResult(
                content=[
                    TextContent(type="text", text=result["content"][0]["text"]),
                ],
                structuredContent=result.get("structuredContent"),
                isError=result.get("isError", False),
            )

        wrapper.__name__ = tool.name
        wrapper.__doc__ = mcp_tool.get("description", "")
        decorator = app.tool(
            name=tool.name,
            description=mcp_tool.get("description", ""),
            annotations=mcp_tool.get("annotations"),
        )
        decorator(wrapper)

    @staticmethod
    def _register_fastmcp_resource(app: Any, resource: MCPResource) -> None:
        def reader() -> str:
            return resource.text

        reader.__name__ = f"read_{resource.name.replace('/', '_').replace('.', '_')}"
        reader.__doc__ = resource.description
        app.resource(resource.uri, name=resource.name, mime_type=resource.mime_type)(reader)

    def _register_fastmcp_prompt(self, app: Any, prompt: MCPPrompt) -> None:
        def renderer(**kwargs: Any) -> str:
            return prompt.render(**kwargs)

        renderer.__name__ = prompt.name
        renderer.__doc__ = prompt.description
        app.prompt(name=prompt.name, description=prompt.description)(renderer)

    def run(
        self,
        *,
        transport: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """Run the FastMCP server."""
        app = self.build_fastmcp()
        selected = transport or self.config.transport
        if selected == "streamable-http":
            app.settings.host = host or self.config.host
            app.settings.port = port or self.config.port
            app.settings.streamable_http_path = self.config.path
        app.run(transport=selected)
