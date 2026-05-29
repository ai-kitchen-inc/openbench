"""Standard MCP server registry for General Chat."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.mcp.adapters import MCPToolAdapter
from openbench.mcp.client import MCPClient
from openbench.mcp.config import MCPClientConfig, MCPPolicyConfig, MCPServerConnectionConfig
from openbench.mcp.policy import redact_secrets
from openbench.mcp.schema import mcp_tool_to_openai_schema
from openbench.mcp.standard_config import MCPConfigImportError, parse_standard_mcp_json
from openbench.mcp.toolhive import ToolHiveWorkload, toolhive_workload_to_mcp_config

logger = logging.getLogger(__name__)


class MCPRegistryError(ValueError):
    """User-safe MCP registry error."""


SERVER_STATUSES = {"enabled", "disabled", "running", "stopped", "failed", "unavailable"}


@dataclass
class RegisteredMCPTool:
    name: str
    namespaced_name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    discovered_at: str | None = None
    provider_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespacedName": self.namespaced_name,
            "namespaced_name": self.namespaced_name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "input_schema": self.input_schema,
            "enabled": self.enabled,
            "discoveredAt": self.discovered_at,
            "discovered_at": self.discovered_at,
            "providerWarning": self.provider_warning,
            "provider_warning": self.provider_warning,
        }


@dataclass
class RegisteredMCPServer:
    id: str
    name: str
    config: dict[str, Any]
    source: str = "manual"
    workload_name: str | None = None
    proxy_url: str | None = None
    enabled: bool = True
    status: str = "enabled"
    error: str | None = None
    registered_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    last_discovered_at: str | None = None
    tools: list[RegisteredMCPTool] = field(default_factory=list)

    def to_dict(self, *, detail: bool = False) -> dict[str, Any]:
        display_config = redact_secrets(self.config)
        data = {
            "id": self.id,
            "name": self.name,
            "title": self.name,
            "source": self.source,
            "workloadName": self.workload_name,
            "workload_name": self.workload_name,
            "proxyUrl": self.proxy_url,
            "proxy_url": self.proxy_url,
            "transport": self.config.get("transport", "stdio"),
            "enabled": self.enabled,
            "status": "disabled" if not self.enabled else self.status,
            "error": self.error,
            "registeredAt": self.registered_at,
            "registered_at": self.registered_at,
            "updatedAt": self.updated_at,
            "updated_at": self.updated_at,
            "lastDiscoveredAt": self.last_discovered_at,
            "last_discovered_at": self.last_discovered_at,
            "tools": [tool.to_dict() for tool in self.tools],
            "toolsCount": len(self.tools),
            "tools_count": len(self.tools),
            "enabledToolsCount": sum(1 for tool in self.tools if tool.enabled),
            "enabled_tools_count": sum(1 for tool in self.tools if tool.enabled),
            "displayConfig": display_config,
            "display_config": display_config,
        }
        if detail:
            data["config"] = display_config
        return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _server_id(name: str) -> str:
    return f"server-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}"


def _connection_to_dict(config: MCPServerConnectionConfig) -> dict[str, Any]:
    return config.model_dump(exclude_none=True)


def _tool_from_schema(server_name: str, raw: dict[str, Any], previous: RegisteredMCPTool | None) -> RegisteredMCPTool:
    tool_name = str(raw.get("name") or "").strip()
    namespaced = f"{server_name}.{tool_name}"
    return RegisteredMCPTool(
        name=tool_name,
        namespaced_name=namespaced,
        description=str(raw.get("description") or ""),
        input_schema=dict(raw.get("inputSchema") or {}),
        enabled=previous.enabled if previous is not None else True,
        discovered_at=_now(),
        provider_warning=_provider_schema_warning(namespaced, raw),
    )


class MCPServerRegistryStore:
    """JSON-backed registry for user-provided MCP server configs."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve() / "mcp_registry"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "servers.json"

    def import_config_json(self, raw_json: str) -> dict[str, Any]:
        try:
            config = parse_standard_mcp_json(raw_json)
        except MCPConfigImportError as exc:
            raise MCPRegistryError(str(exc)) from exc

        state = self._load_state()
        now = _now()
        servers_by_id = {item["id"]: item for item in state["servers"]}
        tools = state.setdefault("tools", {})

        for name, connection in config.servers.items():
            server_id = _server_id(name)
            config_dict = _connection_to_dict(connection)
            existing = servers_by_id.get(server_id)
            previous_config = existing.get("config") if existing else None
            config_changed = previous_config != config_dict
            server_state = {
                "id": server_id,
                "name": name,
                "config": config_dict,
                "enabled": existing.get("enabled", True) if existing else True,
                "status": existing.get("status", "enabled") if existing else "enabled",
                "error": None,
                "registered_at": existing.get("registered_at", now) if existing else now,
                "updated_at": now,
                "last_discovered_at": None if config_changed else existing.get("last_discovered_at") if existing else None,
            }
            servers_by_id[server_id] = server_state
            if config_changed:
                tools.pop(server_id, None)

        state["servers"] = sorted(servers_by_id.values(), key=lambda item: item["name"])
        self._save_state(state)
        return self.list_payload()

    def import_toolhive_workloads(self, workloads: list[ToolHiveWorkload]) -> dict[str, Any]:
        """Register running ToolHive workloads as user-enabled MCP servers."""
        state = self._load_state()
        now = _now()
        servers_by_id = {item["id"]: item for item in state["servers"]}
        tools = state.setdefault("tools", {})

        for workload in workloads:
            connection = toolhive_workload_to_mcp_config(workload)
            name = connection.namespace or workload.name
            server_id = _server_id(name)
            config_dict = _connection_to_dict(connection)
            existing = servers_by_id.get(server_id)
            previous_config = existing.get("config") if existing else None
            config_changed = previous_config != config_dict
            servers_by_id[server_id] = {
                "id": server_id,
                "name": name,
                "source": "toolhive",
                "workload_name": workload.name,
                "proxy_url": workload.url,
                "config": config_dict,
                "enabled": existing.get("enabled", True) if existing else True,
                "status": workload.status if workload.status else "running",
                "error": None,
                "registered_at": existing.get("registered_at", now) if existing else now,
                "updated_at": now,
                "last_discovered_at": None
                if config_changed
                else existing.get("last_discovered_at")
                if existing
                else None,
            }
            if config_changed:
                tools.pop(server_id, None)

        state["servers"] = sorted(servers_by_id.values(), key=lambda item: item["name"])
        self._save_state(state)
        return self.list_payload()

    def list_payload(self) -> dict[str, Any]:
        state = self._load_state()
        servers = [self._server_from_state(item, state).to_dict() for item in state["servers"]]
        return {"servers": servers}

    def get_server(self, server_id: str) -> RegisteredMCPServer:
        state = self._load_state()
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        return self._server_from_state(item, state)

    def remove_server(self, server_id: str) -> None:
        state = self._load_state()
        state["servers"] = [item for item in state["servers"] if item.get("id") != server_id]
        state.setdefault("tools", {}).pop(server_id, None)
        self._save_state(state)

    def set_server_enabled(self, server_id: str, enabled: bool) -> RegisteredMCPServer:
        state = self._load_state()
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        item["enabled"] = bool(enabled)
        item["status"] = "enabled" if enabled else "disabled"
        item["error"] = None if enabled else item.get("error")
        item["updated_at"] = _now()
        self._save_state(state)
        return self.get_server(server_id)

    def set_tool_enabled(self, server_id: str, tool_name: str, enabled: bool) -> RegisteredMCPServer:
        state = self._load_state()
        if self._find_server(state, server_id) is None:
            raise KeyError(server_id)
        tool_state = state.setdefault("tools", {}).setdefault(server_id, {})
        if tool_name not in tool_state:
            raise KeyError(tool_name)
        tool_state[tool_name]["enabled"] = bool(enabled)
        self._save_state(state)
        return self.get_server(server_id)

    def discover_server(self, server_id: str) -> RegisteredMCPServer:
        state = self._load_state()
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        if not item.get("enabled", True):
            item["status"] = "disabled"
            self._save_state(state)
            return self._server_from_state(item, state)
        try:
            discovered = self._discover_single(item)
            previous = {
                name: RegisteredMCPTool(
                    name=tool["name"],
                    namespaced_name=tool["namespaced_name"],
                    description=tool.get("description", ""),
                    input_schema=tool.get("input_schema") or {},
                    enabled=bool(tool.get("enabled", True)),
                    discovered_at=tool.get("discovered_at"),
                )
                for name, tool in state.setdefault("tools", {}).get(server_id, {}).items()
            }
            discovered_tools = {
                raw_name: asdict(_tool_from_schema(item["name"], schema, previous.get(raw_name)))
                for raw_name, schema in discovered.items()
            }
            state.setdefault("tools", {})[server_id] = discovered_tools
            item["status"] = "running"
            item["error"] = None
            item["last_discovered_at"] = _now()
            item["updated_at"] = _now()
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = _safe_error(exc)
            item["updated_at"] = _now()
        self._save_state(state)
        return self._server_from_state(item, state)

    def build_enabled_client_config(self) -> MCPClientConfig:
        state = self._load_state()
        servers: dict[str, MCPServerConnectionConfig] = {}
        for item in state["servers"]:
            if not item.get("enabled", True):
                continue
            servers[item["name"]] = MCPServerConnectionConfig.model_validate(item["config"])
        return MCPClientConfig(
            servers=servers,
            policy=MCPPolicyConfig(
                allow_remote_servers=True,
                require_approval_for_risks=[
                    "write",
                    "artifact_write",
                    "external_network",
                    "destructive",
                ],
            ),
        )

    def load_enabled_tool_adapters(self) -> tuple[list[MCPToolAdapter], dict[str, Any]]:
        state = self._load_state()
        adapters: list[MCPToolAdapter] = []
        summaries: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for item in state["servers"]:
            if not item.get("enabled", True):
                continue
            server_config = MCPServerConnectionConfig.model_validate(item["config"])
            client = MCPClient(
                MCPClientConfig(
                    servers={item["name"]: server_config},
                    policy=MCPPolicyConfig(
                        allow_remote_servers=True,
                        require_approval_for_risks=[
                            "write",
                            "artifact_write",
                            "external_network",
                            "destructive",
                        ],
                    ),
                )
            )
            try:
                discovered = client.discover_sync(refresh=True)
                server = discovered.servers[item["name"]]
                previous_tools = state.setdefault("tools", {}).get(item["id"], {})
                enabled_by_name = {
                    name: bool(tool.get("enabled", True)) for name, tool in previous_tools.items()
                }
                state["tools"][item["id"]] = {
                    name: asdict(
                        _tool_from_schema(
                            item["name"],
                            schema,
                            RegisteredMCPTool(
                                name=name,
                                namespaced_name=f"{item['name']}.{name}",
                                enabled=enabled_by_name.get(name, True),
                            ),
                        )
                    )
                    for name, schema in server.tools.items()
                }
                item["status"] = "running"
                item["error"] = None
                item["last_discovered_at"] = _now()
                item["updated_at"] = _now()
                for tool_name, tool_schema in server.tools.items():
                    if not state["tools"][item["id"]][tool_name].get("enabled", True):
                        continue
                    namespaced = f"{item['name']}.{tool_name}"
                    adapter = MCPToolAdapter(
                        client=client,
                        namespaced_name=namespaced,
                        tool_schema=tool_schema,
                        approved=True,
                        timeout_seconds=server_config.timeout_seconds,
                    )
                    adapters.append(adapter)
                    summaries.append(
                        {
                            "server": item["name"],
                            "name": namespaced,
                            "adapter_name": adapter.name,
                            "description": tool_schema.get("description", ""),
                            "enabled": True,
                            "timeout_seconds": server_config.timeout_seconds,
                            "provider_warning": state["tools"][item["id"]][tool_name].get(
                                "provider_warning"
                            ),
                        }
                    )
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = _safe_error(exc)
                item["updated_at"] = _now()
                errors.append({"server": item["name"], "error": item["error"] or "MCP discovery failed."})
                with suppress(Exception):
                    client.close_sync()

        self._save_state(state)
        return adapters, {
            "enabled": bool(adapters or errors),
            "mode": "registry",
            "registry_root": str(self.root),
            "tools": summaries,
            "errors": errors,
            "error": "; ".join(f"{item['server']}: {item['error']}" for item in errors) or None,
        }

    def _discover_single(self, item: dict[str, Any]) -> dict[str, dict[str, Any]]:
        client = MCPClient(
            MCPClientConfig(
                servers={item["name"]: MCPServerConnectionConfig.model_validate(item["config"])},
                policy=MCPPolicyConfig(allow_remote_servers=True),
            )
        )
        discovered = client.discover_and_close_sync(refresh=True)
        return discovered.servers[item["name"]].tools

    def _server_from_state(self, item: dict[str, Any], state: dict[str, Any]) -> RegisteredMCPServer:
        raw_tools = state.setdefault("tools", {}).get(item["id"], {})
        tools = [
            RegisteredMCPTool(
                name=tool.get("name", name),
                namespaced_name=tool.get("namespaced_name") or tool.get("namespacedName") or f"{item['name']}.{name}",
                description=tool.get("description", ""),
                input_schema=tool.get("input_schema") or tool.get("inputSchema") or {},
                enabled=bool(tool.get("enabled", True)),
                discovered_at=tool.get("discovered_at") or tool.get("discoveredAt"),
                provider_warning=tool.get("provider_warning") or tool.get("providerWarning"),
            )
            for name, tool in sorted(raw_tools.items())
        ]
        return RegisteredMCPServer(
            id=item["id"],
            name=item["name"],
            config=dict(item.get("config") or {}),
            source=str(item.get("source") or "manual"),
            workload_name=item.get("workload_name") or item.get("workloadName"),
            proxy_url=item.get("proxy_url") or item.get("proxyUrl"),
            enabled=bool(item.get("enabled", True)),
            status=str(item.get("status") or "enabled"),
            error=item.get("error"),
            registered_at=item.get("registered_at", _now()),
            updated_at=item.get("updated_at", _now()),
            last_discovered_at=item.get("last_discovered_at"),
            tools=tools,
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"servers": [], "tools": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load MCP server registry")
            return {"servers": [], "tools": {}}
        data.setdefault("servers", [])
        data.setdefault("tools", {})
        return data

    def _save_state(self, state: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    @staticmethod
    def _find_server(state: dict[str, Any], server_id: str) -> dict[str, Any] | None:
        return next((item for item in state.get("servers", []) if item.get("id") == server_id), None)


def _safe_error(exc: BaseException) -> str:
    return str(redact_secrets(str(exc) or exc.__class__.__name__))


def _provider_schema_warning(namespaced_name: str, tool_schema: dict[str, Any]) -> str | None:
    try:
        from google.genai import types
    except ImportError:
        return None
    try:
        function = mcp_tool_to_openai_schema(tool_schema, namespaced_name=namespaced_name)["function"]
        types.FunctionDeclaration(
            name=function["name"],
            description=function.get("description", ""),
            parameters=function.get("parameters"),
        )
    except Exception as exc:
        return f"Tool schema is unavailable to Gemini until simplified: {_safe_error(exc)}"
    return None
