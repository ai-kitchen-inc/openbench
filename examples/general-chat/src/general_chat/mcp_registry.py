"""Standard MCP server registry for General Chat."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.mcp.adapters import MCPToolAdapter
from openbench.mcp.client import MCPClient, create_single_server_client
from openbench.mcp.config import (
    MCPClientConfig,
    MCPPolicyConfig,
    MCPServerConfig,
    MCPServerConnectionConfig,
)
from openbench.mcp.policy import redact_secrets
from openbench.mcp.schema import mcp_tool_to_openai_schema
from openbench.mcp.server import OpenBenchMCPServer
from openbench.mcp.standard_config import MCPConfigImportError, parse_standard_mcp_json
from openbench.mcp.toolhive import ToolHiveWorkload, toolhive_workload_to_mcp_config
from openbench.mcp.transports import InMemoryMCPTransport

logger = logging.getLogger(__name__)


class MCPRegistryError(ValueError):
    """User-safe MCP registry error."""


SERVER_STATUSES = {
    "enabled",
    "disabled",
    "running",
    "stopped",
    "failed",
    "unavailable",
    "empty",
    "invalid",
    "registered",
}
MCP_PROVIDER_KINDS = {"docker", "toolhive", "internal", "manual"}
INTERNAL_MCP_SERVER_NAME = "openbench"
INTERNAL_MCP_SERVER_ID = "internal-openbench"
INTERNAL_MCP_SOURCE = "internal"
_DEFAULT_INTERNAL_APPROVED_TOOLS = {
    "filter_records",
    "distinct_values",
    "group_and_aggregate",
    "top_n_records",
}


@dataclass
class RegisteredMCPTool:
    name: str
    namespaced_name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    discovered_at: str | None = None
    provider_warning: str | None = None
    status: str = "enabled"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    loaded: bool = False
    registered_tool_name: str | None = None

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
            "status": "disabled" if not self.enabled else self.status,
            "diagnostics": self.diagnostics,
            "loaded": self.loaded,
            "registeredToolName": self.registered_tool_name,
            "registered_tool_name": self.registered_tool_name,
        }


@dataclass
class RegisteredMCPServer:
    id: str
    name: str
    config: dict[str, Any]
    source: str = "manual"
    provider_kind: str = "manual"
    source_type: str = "manual"
    server_namespace: str | None = None
    is_managed: bool = False
    workload_name: str | None = None
    proxy_url: str | None = None
    enabled: bool = True
    status: str = "enabled"
    error: str | None = None
    registered_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    last_discovered_at: str | None = None
    tools: list[RegisteredMCPTool] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, detail: bool = False) -> dict[str, Any]:
        display_config = redact_secrets(self.config)
        data = {
            "id": self.id,
            "name": self.name,
            "title": self.name,
            "source": self.source,
            "providerKind": self.provider_kind,
            "provider_kind": self.provider_kind,
            "sourceType": self.source_type,
            "source_type": self.source_type,
            "serverNamespace": self.server_namespace or self.name,
            "server_namespace": self.server_namespace or self.name,
            "isManaged": self.is_managed,
            "is_managed": self.is_managed,
            "workloadName": self.workload_name,
            "workload_name": self.workload_name,
            "proxyUrl": self.proxy_url,
            "proxy_url": self.proxy_url,
            "transport": self.config.get("transport", "stdio"),
            "enabled": self.enabled,
            "status": "disabled" if not self.enabled else self.status,
            "error": self.error,
            "diagnostics": self.diagnostics,
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


def _provider_kind_for_source(source: str, config: dict[str, Any]) -> str:
    if source in {"toolhive", "internal"}:
        return source
    command = str(config.get("command") or "").strip().lower()
    if command in {"docker", "docker.exe"} or command.endswith("\\docker.exe"):
        return "docker"
    if source in MCP_PROVIDER_KINDS:
        return source
    return "manual"


def _source_type_for_config(config: dict[str, Any], fallback: str = "manual") -> str:
    provider_kind = _provider_kind_for_source(fallback, config)
    return provider_kind if provider_kind in MCP_PROVIDER_KINDS else fallback


def _connection_to_dict(config: MCPServerConnectionConfig) -> dict[str, Any]:
    return config.model_dump(exclude_none=True)


def _server_namespace(item: dict[str, Any], config: MCPServerConnectionConfig) -> str:
    return config.namespace or str(item["name"])


def _internal_enabled_tool_names() -> set[str]:
    raw = os.getenv(
        "GENERAL_CHAT_MCP_APPROVED_TOOLS",
        "openbench.filter_records,"
        "openbench.distinct_values,"
        "openbench.group_and_aggregate,"
        "openbench.top_n_records",
    )
    return {
        part.split(".", 1)[-1].strip()
        for part in raw.split(",")
        if part.strip()
    } or set(_DEFAULT_INTERNAL_APPROVED_TOOLS)


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


def _registered_tool_from_state(
    raw: dict[str, Any] | None,
    namespace: str,
    fallback_name: str,
) -> RegisteredMCPTool | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or fallback_name)
    return RegisteredMCPTool(
        name=name,
        namespaced_name=raw.get("namespaced_name") or raw.get("namespacedName") or f"{namespace}.{name}",
        description=str(raw.get("description") or ""),
        input_schema=raw.get("input_schema") or raw.get("inputSchema") or {},
        enabled=bool(raw.get("enabled", True)),
        discovered_at=raw.get("discovered_at") or raw.get("discoveredAt"),
        provider_warning=raw.get("provider_warning") or raw.get("providerWarning"),
        status=str(raw.get("status") or "enabled"),
        diagnostics=dict(raw.get("diagnostics") or {}),
        loaded=bool(raw.get("loaded", False)),
        registered_tool_name=raw.get("registered_tool_name") or raw.get("registeredToolName"),
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
            source_type = _source_type_for_config(
                config_dict,
                existing.get("source", "manual") if existing else "manual",
            )
            previous_config = existing.get("config") if existing else None
            config_changed = previous_config != config_dict
            logger.info(
                "mcp.registry.import_config server=%s changed=%s enabled=%s",
                name,
                config_changed,
                existing.get("enabled", True) if existing else True,
            )
            server_state = {
                "id": server_id,
                "name": name,
                "config": config_dict,
                "source": source_type,
                "provider_kind": _provider_kind_for_source(source_type, config_dict),
                "source_type": source_type,
                "server_namespace": connection.namespace or name,
                "is_managed": False,
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
            logger.info(
                "mcp.registry.import_toolhive server=%s workload=%s changed=%s enabled=%s",
                name,
                workload.name,
                config_changed,
                existing.get("enabled", True) if existing else True,
            )
            servers_by_id[server_id] = {
                "id": server_id,
                "name": name,
                "source": "toolhive",
                "provider_kind": "toolhive",
                "source_type": "toolhive",
                "server_namespace": connection.namespace or name,
                "is_managed": False,
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
        self._ensure_internal_server_state(state)
        self._save_state(state)
        servers = [self._server_from_state(item, state).to_dict() for item in state["servers"]]
        return {"servers": servers}

    def get_server(self, server_id: str) -> RegisteredMCPServer:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        self._save_state(state)
        return self._server_from_state(item, state)

    def remove_server(self, server_id: str) -> None:
        state = self._load_state()
        item = self._find_server(state, server_id)
        if item is not None and item.get("is_managed"):
            raise MCPRegistryError("Managed MCP servers cannot be removed.")
        state["servers"] = [item for item in state["servers"] if item.get("id") != server_id]
        state.setdefault("tools", {}).pop(server_id, None)
        self._save_state(state)

    def set_server_enabled(self, server_id: str, enabled: bool) -> RegisteredMCPServer:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        item["enabled"] = bool(enabled)
        item["status"] = "enabled" if enabled else "disabled"
        item["error"] = None if enabled else item.get("error")
        item["updated_at"] = _now()
        logger.info(
            "mcp.registry.set_server_enabled server=%s server_id=%s enabled=%s",
            item["name"],
            server_id,
            item["enabled"],
        )
        self._save_state(state)
        return self.get_server(server_id)

    def set_tool_enabled(self, server_id: str, tool_name: str, enabled: bool) -> RegisteredMCPServer:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        tool_state = state.setdefault("tools", {}).setdefault(server_id, {})
        if tool_name not in tool_state:
            raise KeyError(tool_name)
        tool_state[tool_name]["enabled"] = bool(enabled)
        logger.info(
            "mcp.registry.set_tool_enabled server=%s server_id=%s tool=%s enabled=%s",
            item["name"],
            server_id,
            tool_name,
            bool(enabled),
        )
        self._save_state(state)
        return self.get_server(server_id)

    def discover_server(self, server_id: str) -> RegisteredMCPServer:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        item = self._find_server(state, server_id)
        if item is None:
            raise KeyError(server_id)
        if not item.get("enabled", True):
            item["status"] = "disabled"
            self._save_state(state)
            return self._server_from_state(item, state)
        try:
            if item.get("provider_kind") == "internal":
                namespace = INTERNAL_MCP_SERVER_NAME
            else:
                server_config = MCPServerConnectionConfig.model_validate(item["config"])
                namespace = _server_namespace(item, server_config)
            discovered = self._discover_single(item)
            previous = {
                name: _registered_tool_from_state(tool, namespace, name)
                for name, tool in state.setdefault("tools", {}).get(server_id, {}).items()
            }
            discovered_tools = {
                raw_name: asdict(_tool_from_schema(namespace, schema, previous.get(raw_name)))
                for raw_name, schema in discovered.items()
            }
            state.setdefault("tools", {})[server_id] = discovered_tools
            item["status"] = "running" if discovered_tools else "empty"
            item["error"] = None if discovered_tools else "MCP server is reachable but exposes no tools."
            item["diagnostics"] = {
                "provider": item.get("provider_kind") or item.get("source") or "manual",
                "server": item.get("name"),
                "source_type": item.get("source_type") or item.get("source") or "manual",
                "tools_discovered": len(discovered_tools),
                "tools_registered": 0,
                "error": item["error"],
            }
            item["last_discovered_at"] = _now()
            item["updated_at"] = _now()
            logger.info(
                "mcp.registry.discover provider=%s source=%s server=%s namespace=%s discovered=%d enabled=%d",
                item.get("provider_kind"),
                item.get("source_type") or item.get("source"),
                item["name"],
                namespace,
                len(discovered_tools),
                sum(1 for tool in discovered_tools.values() if tool.get("enabled", True)),
            )
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = _safe_error(exc)
            item["diagnostics"] = {
                "provider": item.get("provider_kind") or item.get("source") or "manual",
                "server": item.get("name"),
                "source_type": item.get("source_type") or item.get("source") or "manual",
                "tools_discovered": 0,
                "tools_registered": 0,
                "connection_error": item["error"],
            }
            item["updated_at"] = _now()
            logger.warning(
                "mcp.registry.discover_failed provider=%s source=%s server=%s error=%s",
                item.get("provider_kind"),
                item.get("source_type") or item.get("source"),
                item.get("name"),
                item["error"],
            )
        self._save_state(state)
        return self._server_from_state(item, state)

    def build_enabled_client_config(self) -> MCPClientConfig:
        state = self._load_state()
        servers: dict[str, MCPServerConnectionConfig] = {}
        for item in state["servers"]:
            if not item.get("enabled", True):
                continue
            if item.get("provider_kind") == "internal":
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
        self._ensure_internal_server_state(state)
        adapters: list[MCPToolAdapter] = []
        summaries: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        enabled_tool_candidates = 0

        for item in state["servers"]:
            provider = str(item.get("provider_kind") or item.get("source") or "manual")
            source_type = str(item.get("source_type") or item.get("source") or provider)
            if not item.get("enabled", True):
                logger.info(
                    "mcp.registry.load.skip_disabled_server provider=%s source=%s server=%s",
                    provider,
                    source_type,
                    item.get("name"),
                )
                continue

            namespace = str(item.get("server_namespace") or item.get("name") or "")
            client: MCPClient | None = None
            try:
                client, namespace, server_config = self._build_client_for_item(item)
                previous_tools = state.setdefault("tools", {}).get(item["id"], {})
                discovered = self._discover_with_client(item, client, namespace)
                discovered_tools = {
                    raw_name: asdict(
                        _tool_from_schema(
                            namespace,
                            schema,
                            _registered_tool_from_state(previous_tools.get(raw_name), namespace, raw_name),
                        )
                    )
                    for raw_name, schema in discovered.items()
                }
                state["tools"][item["id"]] = discovered_tools
                tools_discovered = len(discovered_tools)
                if tools_discovered == 0:
                    item["status"] = "empty"
                    item["error"] = "MCP server is reachable but exposes no tools."
                    diagnostic = {
                        "provider": provider,
                        "server": item.get("name"),
                        "source_type": source_type,
                        "tools_discovered": 0,
                        "tools_registered": 0,
                        "error": item["error"],
                    }
                    diagnostics.append(diagnostic)
                    item["diagnostics"] = diagnostic
                    logger.warning(
                        "mcp.registry.load.empty provider=%s source=%s server=%s",
                        provider,
                        source_type,
                        item.get("name"),
                    )
                    continue

                item["status"] = "running"
                item["error"] = None
                item["last_discovered_at"] = _now()
                item["updated_at"] = _now()
                enabled_count = 0
                invalid_count = 0
                for tool_name, tool_state in sorted(discovered_tools.items()):
                    if not tool_state.get("enabled", True):
                        tool_state["status"] = "disabled"
                        tool_state["loaded"] = False
                        tool_state["registered_tool_name"] = None
                        continue
                    enabled_count += 1
                    enabled_tool_candidates += 1
                    persisted_name = str(tool_state.get("name") or tool_name)
                    tool_schema = {
                        "name": persisted_name,
                        "description": str(tool_state.get("description") or ""),
                        "inputSchema": tool_state.get("input_schema")
                        or tool_state.get("inputSchema")
                        or {},
                    }
                    namespaced = f"{namespace}.{persisted_name}"
                    adapter = MCPToolAdapter(
                        client=client,
                        namespaced_name=namespaced,
                        tool_schema=tool_schema,
                        approved=True,
                        timeout_seconds=server_config.timeout_seconds
                        if server_config is not None
                        else None,
                        close_after_execute=provider != "internal",
                    )
                    try:
                        adapter.get_schema()
                    except Exception as exc:
                        invalid_count += 1
                        error = _safe_error(exc)
                        tool_state["status"] = "invalid"
                        tool_state["diagnostics"] = {"schema_validation_error": error}
                        tool_state["loaded"] = False
                        tool_state["registered_tool_name"] = None
                        errors.append(
                            {
                                "provider": provider,
                                "server": item["name"],
                                "tool": persisted_name,
                                "error": error,
                                "category": "invalid_tool_schema",
                            }
                        )
                        logger.warning(
                            "mcp.registry.load.invalid_tool provider=%s source=%s server=%s tool=%s error=%s",
                            provider,
                            source_type,
                            item.get("name"),
                            persisted_name,
                            error,
                        )
                        continue
                    tool_state["status"] = "enabled"
                    tool_state["loaded"] = False
                    tool_state["registered_tool_name"] = adapter.name
                    adapters.append(adapter)
                    summaries.append(
                        {
                            "server": item["name"],
                            "provider": provider,
                            "source_type": source_type,
                            "name": namespaced,
                            "adapter_name": adapter.name,
                            "description": tool_schema.get("description", ""),
                            "enabled": True,
                            "timeout_seconds": server_config.timeout_seconds
                            if server_config is not None
                            else None,
                            "provider_warning": tool_state.get("provider_warning"),
                        }
                    )
                item["status"] = "invalid" if enabled_count and invalid_count == enabled_count else "running"
                item["error"] = (
                    "All enabled MCP tools from this server have invalid schemas."
                    if item["status"] == "invalid"
                    else None
                )
                diagnostic = {
                    "provider": provider,
                    "server": item.get("name"),
                    "source_type": source_type,
                    "tools_discovered": tools_discovered,
                    "tools_enabled": enabled_count,
                    "tools_registered": 0,
                    "invalid_tools": invalid_count,
                    "error": item["error"],
                }
                diagnostics.append(diagnostic)
                item["diagnostics"] = diagnostic
                logger.info(
                    "mcp.registry.load provider=%s source=%s server=%s namespace=%s discovered=%d enabled=%d adapters=%d invalid=%d",
                    provider,
                    source_type,
                    item["name"],
                    namespace,
                    tools_discovered,
                    enabled_count,
                    len([entry for entry in summaries if entry.get("server") == item["name"]]),
                    invalid_count,
                )
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = _safe_error(exc)
                item["updated_at"] = _now()
                error_payload = {
                    "provider": provider,
                    "server": item["name"],
                    "source_type": source_type,
                    "error": item["error"] or "MCP discovery failed.",
                    "category": "server_unreachable",
                }
                errors.append(error_payload)
                item["diagnostics"] = {
                    **error_payload,
                    "tools_discovered": 0,
                    "tools_registered": 0,
                    "connection_error": error_payload["error"],
                }
                diagnostics.append(item["diagnostics"])
                logger.warning(
                    "mcp.registry.load_failed provider=%s source=%s server=%s namespace=%s error=%s",
                    provider,
                    source_type,
                    item.get("name"),
                    namespace,
                    item["error"],
                )
                if client is not None:
                    with suppress(Exception):
                        client.close_sync()

        self._save_state(state)
        return adapters, {
            "enabled": enabled_tool_candidates > 0 or bool(errors),
            "mode": "registry",
            "registry_root": str(self.root),
            "tools": summaries,
            "errors": errors,
            "diagnostics": diagnostics,
            "enabled_tool_count": enabled_tool_candidates,
            "registered_tool_count": 0,
            "error": "; ".join(
                f"{item.get('provider', 'mcp')}/{item['server']}: {item['error']}"
                for item in errors
            )
            or None,
        }

    def _discover_single(self, item: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if item.get("provider_kind") == "internal":
            client, namespace, _server_config = self._build_client_for_item(item)
            return self._discover_with_client(item, client, namespace)

        server_config = MCPServerConnectionConfig.model_validate(item["config"])
        namespace = _server_namespace(item, server_config)
        client = MCPClient(
            MCPClientConfig(
                servers={item["name"]: server_config},
                policy=MCPPolicyConfig(allow_remote_servers=True),
            )
        )
        discovered = client.discover_and_close_sync(refresh=True)
        server = discovered.servers.get(namespace)
        if server is None and len(discovered.servers) == 1:
            server = next(iter(discovered.servers.values()))
        if server is None:
            raise MCPRegistryError(
                f"MCP server {item['name']!r} discovered no server namespace {namespace!r}."
            )
        return server.tools

    def _build_client_for_item(
        self,
        item: dict[str, Any],
    ) -> tuple[MCPClient, str, MCPServerConnectionConfig | None]:
        if item.get("provider_kind") == "internal":
            server_config = MCPServerConfig(name=INTERNAL_MCP_SERVER_NAME, include_sdk_tools=True)
            server = OpenBenchMCPServer(server_config)
            namespace = server_config.name
            client = create_single_server_client(namespace, InMemoryMCPTransport(server))
            return client, namespace, None

        server_config = MCPServerConnectionConfig.model_validate(item["config"])
        namespace = _server_namespace(item, server_config)
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
        return client, namespace, server_config

    def _discover_with_client(
        self,
        item: dict[str, Any],
        client: MCPClient,
        namespace: str,
    ) -> dict[str, dict[str, Any]]:
        discovered = client.discover_sync(refresh=True)
        server = discovered.servers.get(namespace)
        if server is None and len(discovered.servers) == 1:
            server = next(iter(discovered.servers.values()))
        if server is None:
            raise MCPRegistryError(
                f"MCP server {item['name']!r} discovered no server namespace {namespace!r}."
            )
        return server.tools

    def _ensure_internal_server_state(self, state: dict[str, Any]) -> None:
        servers = state.setdefault("servers", [])
        tools = state.setdefault("tools", {})
        item = self._find_server(state, INTERNAL_MCP_SERVER_ID)
        now = _now()
        if item is None:
            item = {
                "id": INTERNAL_MCP_SERVER_ID,
                "name": INTERNAL_MCP_SERVER_NAME,
                "config": {
                    "transport": "in-memory",
                    "namespace": INTERNAL_MCP_SERVER_NAME,
                    "include_sdk_tools": True,
                },
                "source": INTERNAL_MCP_SOURCE,
                "provider_kind": "internal",
                "source_type": INTERNAL_MCP_SOURCE,
                "server_namespace": INTERNAL_MCP_SERVER_NAME,
                "is_managed": True,
                "enabled": True,
                "status": "enabled",
                "error": None,
                "registered_at": now,
                "updated_at": now,
                "last_discovered_at": None,
            }
            servers.append(item)
        else:
            item["source"] = INTERNAL_MCP_SOURCE
            item["provider_kind"] = "internal"
            item["source_type"] = INTERNAL_MCP_SOURCE
            item["server_namespace"] = INTERNAL_MCP_SERVER_NAME
            item["is_managed"] = True
            item.setdefault("enabled", True)

        if not tools.get(INTERNAL_MCP_SERVER_ID):
            try:
                discovered = self._discover_single(item)
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = _safe_error(exc)
                item["diagnostics"] = {
                    "provider": "internal",
                    "server": INTERNAL_MCP_SERVER_NAME,
                    "source_type": INTERNAL_MCP_SOURCE,
                    "tools_discovered": 0,
                    "tools_registered": 0,
                    "connection_error": item["error"],
                }
                logger.warning("mcp.registry.internal_discover_failed error=%s", item["error"])
                return
            approved = _internal_enabled_tool_names()
            tools[INTERNAL_MCP_SERVER_ID] = {
                name: asdict(
                    RegisteredMCPTool(
                        name=name,
                        namespaced_name=f"{INTERNAL_MCP_SERVER_NAME}.{name}",
                        description=str(schema.get("description") or ""),
                        input_schema=dict(schema.get("inputSchema") or {}),
                        enabled=name in approved,
                        discovered_at=_now(),
                        provider_warning=_provider_schema_warning(
                            f"{INTERNAL_MCP_SERVER_NAME}.{name}",
                            schema,
                        ),
                        status="enabled" if name in approved else "disabled",
                    )
                )
                for name, schema in discovered.items()
            }
            item["status"] = "running" if discovered else "empty"
            item["error"] = None if discovered else "MCP server is reachable but exposes no tools."
            item["last_discovered_at"] = _now()
            item["updated_at"] = _now()
            item["diagnostics"] = {
                "provider": "internal",
                "server": INTERNAL_MCP_SERVER_NAME,
                "source_type": INTERNAL_MCP_SOURCE,
                "tools_discovered": len(discovered),
                "tools_registered": 0,
                "error": item["error"],
            }

        state["servers"] = sorted(servers, key=lambda entry: (entry.get("is_managed") is True, entry.get("name", "")))

    def mark_runtime_registration(
        self,
        registered_tool_names: set[str],
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> None:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        registered_lookup = set(registered_tool_names)
        diagnostics_by_server = {
            str(item.get("server")): item
            for item in diagnostics or []
            if isinstance(item, dict) and item.get("server")
        }
        for item in state.get("servers", []):
            server_tools = state.setdefault("tools", {}).get(item["id"], {})
            registered_count = 0
            for tool_state in server_tools.values():
                provider_name = tool_state.get("registered_tool_name") or tool_state.get("registeredToolName")
                if provider_name and provider_name in registered_lookup:
                    tool_state["loaded"] = True
                    tool_state["status"] = "registered"
                    registered_count += 1
                elif tool_state.get("enabled", True):
                    tool_state["loaded"] = False
                    if tool_state.get("status") != "invalid":
                        tool_state["status"] = "enabled"
                else:
                    tool_state["loaded"] = False
                    tool_state["status"] = "disabled"
            server_diagnostics = dict(diagnostics_by_server.get(str(item.get("name")), item.get("diagnostics") or {}))
            server_diagnostics["tools_registered"] = registered_count
            item["diagnostics"] = server_diagnostics
            if registered_count:
                item["status"] = "registered"
                item["error"] = None
        self._save_state(state)

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
                status=str(tool.get("status") or "enabled"),
                diagnostics=dict(tool.get("diagnostics") or {}),
                loaded=bool(tool.get("loaded", False)),
                registered_tool_name=tool.get("registered_tool_name") or tool.get("registeredToolName"),
            )
            for name, tool in sorted(raw_tools.items())
        ]
        source = str(item.get("source") or "manual")
        provider_kind = str(
            item.get("provider_kind")
            or item.get("providerKind")
            or _provider_kind_for_source(source, dict(item.get("config") or {}))
        )
        source_type = str(item.get("source_type") or item.get("sourceType") or provider_kind)
        return RegisteredMCPServer(
            id=item["id"],
            name=item["name"],
            config=dict(item.get("config") or {}),
            source=source,
            provider_kind=provider_kind,
            source_type=source_type,
            server_namespace=item.get("server_namespace") or item.get("serverNamespace") or item.get("name"),
            is_managed=bool(item.get("is_managed") or item.get("isManaged")),
            workload_name=item.get("workload_name") or item.get("workloadName"),
            proxy_url=item.get("proxy_url") or item.get("proxyUrl"),
            enabled=bool(item.get("enabled", True)),
            status=str(item.get("status") or "enabled"),
            error=item.get("error"),
            registered_at=item.get("registered_at", _now()),
            updated_at=item.get("updated_at", _now()),
            last_discovered_at=item.get("last_discovered_at"),
            tools=tools,
            diagnostics=dict(item.get("diagnostics") or {}),
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
        self._normalize_state(data)
        return data

    def _save_state(self, state: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _normalize_state(self, state: dict[str, Any]) -> None:
        for item in state.get("servers", []):
            config = dict(item.get("config") or {})
            source = str(item.get("source") or "manual")
            provider_kind = str(
                item.get("provider_kind")
                or item.get("providerKind")
                or _provider_kind_for_source(source, config)
            )
            source_type = str(item.get("source_type") or item.get("sourceType") or provider_kind)
            item["source"] = source_type
            item["provider_kind"] = provider_kind
            item["source_type"] = source_type
            item.setdefault("server_namespace", config.get("namespace") or item.get("name"))
            item.setdefault("is_managed", provider_kind == "internal")
            item.setdefault("diagnostics", {})

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
