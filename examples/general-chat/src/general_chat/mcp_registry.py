"""Standard MCP server registry for General Chat."""

from __future__ import annotations

import builtins
import contextlib
import copy
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbench.core.providers import get_credential_encryption
from openbench.mcp.adapters import MCPToolAdapter
from openbench.mcp.client import MCPClient, create_single_server_client
from openbench.mcp.config import (
    MCPClientConfig,
    MCPPolicyConfig,
    MCPServerConfig,
    MCPServerConnectionConfig,
    expand_env_vars,
)
from openbench.mcp.permissions import MCPPermissionSession, PermissionProvider
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
_SECRET_PLACEHOLDER_RE = re.compile(r"\$\{secret:([A-Za-z0-9_.-]+)\}")
_SECRET_PLACEHOLDER_FULL_RE = re.compile(r"^\$\{secret:([A-Za-z0-9_.-]+)\}$")
_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_DEFAULT_INTERNAL_APPROVED_TOOLS = {
    "filter_records",
    "distinct_values",
    "group_and_aggregate",
    "top_n_records",
}


class MCPSecretStore:
    """Encrypted local storage for MCP secret values."""

    def __init__(self, path: Path):
        self.path = path

    def set(self, server_id: str, key: str, value: str) -> None:
        encryption = get_credential_encryption()
        if not encryption.is_available:
            raise MCPRegistryError(
                "Managed MCP secret storage requires credential encryption. "
                "Install openbench[security] or use a normal ${ENV_VAR} reference for local environment fallback."
            )
        data = self._load()
        secrets = data.setdefault("secrets", {}).setdefault(server_id, {})
        secrets[key] = {
            "value": encryption.encrypt(value),
            "updated_at": _now(),
        }
        self._save(data)

    def get(self, server_id: str, key: str) -> str | None:
        entry = self._load().get("secrets", {}).get(server_id, {}).get(key)
        if not isinstance(entry, dict):
            return None
        encrypted = entry.get("value")
        if not isinstance(encrypted, str):
            return None
        encryption = get_credential_encryption()
        if not encryption.is_available:
            raise MCPRegistryError(
                f"Managed MCP secret {key} cannot be decrypted because credential encryption is unavailable."
            )
        return encryption.decrypt(encrypted)

    def has(self, server_id: str, key: str) -> bool:
        return key in self._load().get("secrets", {}).get(server_id, {})

    def remove_server(self, server_id: str) -> None:
        data = self._load()
        if server_id in data.get("secrets", {}):
            data["secrets"].pop(server_id, None)
            self._save(data)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "secrets": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load MCP secret store")
            return {"version": 1, "secrets": {}}
        data.setdefault("version", 1)
        data.setdefault("secrets", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)


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
    secrets: list[dict[str, Any]] = field(default_factory=list)

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
            "secrets": self.secrets,
            "secretMetadata": self.secrets,
            "secret_metadata": self.secrets,
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


def _normalize_import_secret_values(secret_values: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(secret_values, dict):
        return {}
    return {
        str(key).strip(): value
        for key, value in secret_values.items()
        if str(key).strip() and isinstance(value, str) and value
    }


def _secret_placeholders(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(_SECRET_PLACEHOLDER_RE.findall(value))
    if isinstance(value, dict):
        found: set[str] = set()
        for item in value.values():
            found.update(_secret_placeholders(item))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found.update(_secret_placeholders(item))
        return found
    return set()


def _secret_reference(key: str) -> str:
    return f"${{secret:{key}}}"


def _secret_reference_key(value: str) -> str | None:
    match = _SECRET_PLACEHOLDER_FULL_RE.match(value.strip())
    return match.group(1) if match else None


def _contains_local_env_reference(value: str) -> bool:
    return bool(_ENV_PLACEHOLDER_RE.search(value))


def _policy_to_dict(policy: MCPPolicyConfig) -> dict[str, Any]:
    return policy.model_dump(exclude_none=True)


def _server_namespace(item: dict[str, Any], config: MCPServerConnectionConfig) -> str:
    return config.namespace or str(item["name"])


def _policy_for_items(
    items: list[dict[str, Any]],
    *,
    allow_remote_servers: bool = True,
    require_approval_for_risks: list[str] | None = None,
) -> MCPPolicyConfig:
    max_timeout = 30.0
    max_response_chars = 200_000
    max_concurrency = 8
    allowed_servers: set[str] = set()
    denied_servers: set[str] = set()
    allowed_tools: set[str] = set()
    denied_tools: set[str] = set()
    risk_requirements: set[str] = set(require_approval_for_risks or [])

    for item in items:
        raw_policy = item.get("policy")
        if isinstance(raw_policy, dict):
            try:
                policy = MCPPolicyConfig.model_validate(raw_policy)
            except Exception:
                policy = MCPPolicyConfig()
            max_timeout = max(max_timeout, float(policy.max_timeout_seconds))
            max_response_chars = max(max_response_chars, int(policy.max_response_chars))
            max_concurrency = max(max_concurrency, int(policy.max_concurrency))
            allowed_servers.update(policy.allowed_servers)
            denied_servers.update(policy.denied_servers)
            allowed_tools.update(policy.allowed_tools)
            denied_tools.update(policy.denied_tools)
            risk_requirements.update(policy.require_approval_for_risks)

        try:
            server_config = MCPServerConnectionConfig.model_validate(item.get("config") or {})
        except Exception:
            continue
        max_timeout = max(max_timeout, float(server_config.timeout_seconds))

    return MCPPolicyConfig(
        allowed_servers=sorted(allowed_servers),
        denied_servers=sorted(denied_servers),
        allowed_tools=sorted(allowed_tools),
        denied_tools=sorted(denied_tools),
        require_approval_for_risks=sorted(risk_requirements),
        allow_remote_servers=allow_remote_servers,
        max_timeout_seconds=max_timeout,
        max_response_chars=max_response_chars,
        max_concurrency=max_concurrency,
    )


def _policy_for_item(
    item: dict[str, Any],
    *,
    allow_remote_servers: bool = True,
    require_approval_for_risks: list[str] | None = None,
) -> MCPPolicyConfig:
    return _policy_for_items(
        [item],
        allow_remote_servers=allow_remote_servers,
        require_approval_for_risks=require_approval_for_risks,
    )


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
        self.secret_store = MCPSecretStore(self.root / "secrets.json")

    def import_config_json(
        self,
        raw_json: str,
        *,
        secret_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            config = parse_standard_mcp_json(raw_json)
        except MCPConfigImportError as exc:
            raise MCPRegistryError(str(exc)) from exc

        return self.import_client_config(
            config,
            secret_values=_normalize_import_secret_values(secret_values),
        )

    def import_client_config(
        self,
        config: MCPClientConfig,
        *,
        source: str = "manual",
        secret_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register MCP servers from an already-validated client config."""
        state = self._load_state()
        now = _now()
        servers_by_id = {item["id"]: item for item in state["servers"]}
        tools = state.setdefault("tools", {})
        policy_dict = _policy_to_dict(config.policy)

        for name, connection in config.servers.items():
            server_id = _server_id(name)
            config_dict = _connection_to_dict(connection)
            existing = servers_by_id.get(server_id)
            source_type = _source_type_for_config(
                config_dict,
                existing.get("source", source) if existing else source,
            )
            provider_kind = _provider_kind_for_source(source_type, config_dict)
            secret_config = self._prepare_secret_config(
                server_id=server_id,
                config=config_dict,
                provider_kind=provider_kind,
                existing=existing,
                supplied_secret_values=secret_values or {},
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
                "provider_kind": provider_kind,
                "source_type": source_type,
                "server_namespace": connection.namespace or name,
                "is_managed": False,
                "secrets": secret_config,
                "policy": policy_dict,
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
        self.secret_store.remove_server(server_id)
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
                server_config = MCPServerConnectionConfig.model_validate(
                    self._resolved_config_for_item(item)
                )
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
        except BaseException as exc:
            if _is_process_exit(exc):
                raise
            item["status"] = "failed"
            item["error"] = _safe_error(exc)
            hint = _connection_failure_hint(item, item["error"])
            item["diagnostics"] = {
                "provider": item.get("provider_kind") or item.get("source") or "manual",
                "server": item.get("name"),
                "source_type": item.get("source_type") or item.get("source") or "manual",
                "tools_discovered": 0,
                "tools_registered": 0,
                "connection_error": item["error"],
                **({"hint": hint} if hint else {}),
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
            servers[item["name"]] = MCPServerConnectionConfig.model_validate(
                self._resolved_config_for_item(item)
            )
        return MCPClientConfig(
            servers=servers,
            policy=_policy_for_items(
                [item for item in state["servers"] if item.get("enabled", True)],
                allow_remote_servers=True,
                require_approval_for_risks=[
                    "write",
                    "artifact_write",
                    "external_network",
                    "destructive",
                ],
            ),
        )

    def load_enabled_tool_adapters(
        self,
        server_ids: set[str] | None = None,
        permission_provider: PermissionProvider | None = None,
        permission_session: MCPPermissionSession | None = None,
    ) -> tuple[list[MCPToolAdapter], dict[str, Any]]:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        selected_server_ids = set(server_ids) if server_ids is not None else None
        permission_session = permission_session or MCPPermissionSession(
            permission_provider
        )
        adapters: list[MCPToolAdapter] = []
        summaries: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        enabled_tool_candidates = 0

        for item in state["servers"]:
            if selected_server_ids is not None and item.get("id") not in selected_server_ids:
                continue
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
                runtime_client = client
                if provider != "internal":
                    runtime_client, _runtime_namespace, _runtime_server_config = (
                        self._build_client_for_item(item)
                    )
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
                        client=runtime_client,
                        namespaced_name=namespaced,
                        tool_schema=tool_schema,
                        permission_session=permission_session,
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
                            "server_id": item["id"],
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
            except BaseException as exc:
                if _is_process_exit(exc):
                    raise
                item["status"] = "failed"
                item["error"] = _safe_error(exc)
                item["updated_at"] = _now()
                hint = _connection_failure_hint(item, item["error"])
                error_payload = {
                    "provider": provider,
                    "server": item["name"],
                    "source_type": source_type,
                    "error": item["error"] or "MCP discovery failed.",
                    "category": "server_unreachable",
                    **({"hint": hint} if hint else {}),
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
                    try:
                        client.close_sync()
                    except BaseException as close_exc:
                        if _is_process_exit(close_exc):
                            raise

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

        server_config = MCPServerConnectionConfig.model_validate(self._resolved_config_for_item(item))
        namespace = _server_namespace(item, server_config)
        client = MCPClient(
            MCPClientConfig(
                servers={item["name"]: server_config},
                policy=_policy_for_item(item, allow_remote_servers=True),
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

        server_config = MCPServerConnectionConfig.model_validate(self._resolved_config_for_item(item))
        namespace = _server_namespace(item, server_config)
        client = MCPClient(
            MCPClientConfig(
                servers={item["name"]: server_config},
                policy=_policy_for_item(
                    item,
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

    def _prepare_secret_config(
        self,
        *,
        server_id: str,
        config: dict[str, Any],
        provider_kind: str,
        existing: dict[str, Any] | None,
        supplied_secret_values: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        if provider_kind != "docker":
            return {}

        existing_secrets = dict(existing.get("secrets") or {}) if existing else {}
        secret_config: dict[str, dict[str, Any]] = {}

        def mark_managed(key: str, *, value: str | None = None) -> None:
            if value is not None:
                self.secret_store.set(server_id, key, value)
                secret_config[key] = {
                    "source": "managed",
                    "secret_key": key,
                    "updated_at": _now(),
                }
                return

            supplied = supplied_secret_values.get(key, "")
            if supplied:
                self.secret_store.set(server_id, key, supplied)
                secret_config[key] = {
                    "source": "managed",
                    "secret_key": key,
                    "updated_at": _now(),
                }
                return

            previous = existing_secrets.get(key)
            if (
                isinstance(previous, dict)
                and previous.get("source") == "managed"
                and self.secret_store.has(server_id, key)
            ):
                secret_config[key] = {
                    "source": "managed",
                    "secret_key": key,
                    "updated_at": previous.get("updated_at") or _now(),
                }
                return

            secret_config[key] = {
                "source": "managed",
                "secret_key": key,
                "updated_at": _now(),
            }

        env = config.get("env")
        if not isinstance(env, dict):
            env = {}
            if supplied_secret_values:
                config["env"] = env

        for key, value in sorted(supplied_secret_values.items()):
            existing_value = env.get(key)
            if isinstance(existing_value, str) and _secret_reference_key(existing_value):
                continue
            env[key] = value

        for env_key, raw_value in list(env.items()):
            if not isinstance(raw_value, str) or raw_value == "":
                continue
            explicit_keys = _secret_placeholders(raw_value)
            if explicit_keys:
                for key in sorted(explicit_keys):
                    mark_managed(key)
                continue
            if _contains_local_env_reference(raw_value):
                continue

            secret_key = str(env_key)
            mark_managed(secret_key, value=raw_value)
            env[env_key] = _secret_reference(secret_key)

        for key in sorted(_secret_placeholders(config)):
            if key not in secret_config:
                mark_managed(key)

        return secret_config

    def _resolved_config_for_item(self, item: dict[str, Any]) -> dict[str, Any]:
        config = copy.deepcopy(dict(item.get("config") or {}))
        return expand_env_vars(self._replace_secret_placeholders(config, item))

    def _replace_secret_placeholders(self, value: Any, item: dict[str, Any]) -> Any:
        if isinstance(value, str):
            def replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in dict(item.get("secrets") or {}):
                    raise MCPRegistryError(
                        f"MCP secret {key} is referenced but was not added to the import secrets."
                    )
                secret_value = self.secret_store.get(str(item["id"]), key)
                if not secret_value:
                    raise MCPRegistryError(f"MCP secret {key} is missing from managed storage.")
                return secret_value

            return _SECRET_PLACEHOLDER_RE.sub(replace, value)
        if isinstance(value, dict):
            return {key: self._replace_secret_placeholders(item_value, item) for key, item_value in value.items()}
        if isinstance(value, list):
            return [self._replace_secret_placeholders(item_value, item) for item_value in value]
        return value

    def _discover_with_client(
        self,
        item: dict[str, Any],
        client: MCPClient,
        namespace: str,
    ) -> dict[str, dict[str, Any]]:
        if item.get("provider_kind") == "internal":
            discovered = client.discover_sync(refresh=True)
        else:
            discovered = client.discover_and_close_sync(refresh=True)
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
        server_ids: set[str] | None = None,
    ) -> None:
        state = self._load_state()
        self._ensure_internal_server_state(state)
        selected_server_ids = set(server_ids) if server_ids is not None else None
        registered_lookup = set(registered_tool_names)
        diagnostics_by_server = {
            str(item.get("server")): item
            for item in diagnostics or []
            if isinstance(item, dict) and item.get("server")
        }
        for item in state.get("servers", []):
            if selected_server_ids is not None and item.get("id") not in selected_server_ids:
                continue
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
            secrets=self._secret_metadata_for_item(item),
        )

    def _secret_metadata_for_item(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for key, raw in sorted(dict(item.get("secrets") or {}).items()):
            if not isinstance(raw, dict):
                continue
            secret_key = str(raw.get("secret_key") or raw.get("env_key") or key)
            source = str(raw.get("source") or "managed")
            configured = self.secret_store.has(str(item["id"]), secret_key)
            result.append(
                {
                    "key": secret_key,
                    "secretKey": secret_key,
                    "secret_key": secret_key,
                    "source": source,
                    "configured": configured,
                    "missing": not configured,
                    "status": "configured" if configured else "missing",
                    "value": "***REDACTED***" if configured else "",
                }
            )
        return result

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


def _connection_failure_hint(item: dict[str, Any], error: str) -> str | None:
    config = item.get("config") if isinstance(item.get("config"), dict) else {}
    command = str(config.get("command") or "").lower()
    args = [str(arg) for arg in config.get("args") or []]
    server_name = str(item.get("name") or "")
    if (
        "connection closed" in error.lower()
        and ("docker" in command or any(arg.startswith("openbench/") for arg in args))
    ):
        if server_name == "image_search" or any("image-search-mcp" in arg for arg in args):
            return (
                "The Docker image-search MCP process exited before handshake. Verify "
                "Docker can inspect openbench/image-search-mcp:cpu, then run "
                "`python mcp/image-search-mcp/scripts/test_mcp_server.py --mode docker` "
                "for container stderr and startup details."
            )
        return (
            "The Docker-backed MCP process exited before handshake. Verify the image "
            "exists, Docker is accessible, and the container starts in stdio MCP mode."
        )
    return None


def _is_process_exit(exc: BaseException) -> bool:
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return True
    exception_group = getattr(builtins, "BaseExceptionGroup", None)
    if exception_group is not None and isinstance(exc, exception_group):
        return any(_is_process_exit(item) for item in exc.exceptions)
    return False


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
