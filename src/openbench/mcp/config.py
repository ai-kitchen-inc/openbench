"""Configuration models for OpenBench MCP."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openbench.mcp.schema import normalize_server_name

TransportName = Literal["stdio", "streamable-http", "sse"]


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR}`` and ``${VAR:-default}`` strings."""
    if isinstance(value, str):
        pattern = r"\$\{([^}:]+)(?::-([^}]*))?\}"

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            default = match.group(2) or ""
            return os.environ.get(name, default)

        return re.sub(pattern, replace, value)
    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    return value


class MCPPolicyConfig(BaseModel):
    """Policy configuration shared by MCP server and client paths."""

    model_config = ConfigDict(extra="forbid")

    allowed_servers: list[str] = Field(default_factory=list)
    denied_servers: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    require_approval_for_risks: list[str] = Field(default_factory=list)
    allow_remote_servers: bool = False
    max_timeout_seconds: float = 30.0
    max_response_chars: int = 200_000
    max_concurrency: int = 8


class MCPServerConfig(BaseModel):
    """Configuration for the OpenBench-hosted MCP server."""

    model_config = ConfigDict(extra="forbid")

    name: str = "openbench"
    include_sdk_tools: bool = True
    skills: list[str] = Field(default_factory=list)
    transport: TransportName = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    allow_legacy_sse: bool = False
    require_auth: bool = False
    auth_token_env: str | None = None
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1"])
    policy: MCPPolicyConfig = Field(default_factory=MCPPolicyConfig)

    @model_validator(mode="after")
    def _normalize_name(self) -> MCPServerConfig:
        self.name = normalize_server_name(self.name)
        return self


class MCPServerConnectionConfig(BaseModel):
    """Client-side configuration for one MCP server."""

    model_config = ConfigDict(extra="forbid")

    transport: TransportName = "stdio"
    namespace: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0
    retries: int = 2
    retry_backoff_seconds: float = 0.25
    enabled: bool = True
    allowed: bool = False

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> MCPServerConnectionConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP servers require command")
        if self.transport in {"streamable-http", "sse"} and not self.url:
            raise ValueError(f"{self.transport} MCP servers require url")
        if self.namespace is not None:
            self.namespace = normalize_server_name(self.namespace)
        return self


class MCPClientConfig(BaseModel):
    """Configuration for an MCP client spanning multiple servers."""

    model_config = ConfigDict(extra="forbid")

    servers: dict[str, MCPServerConnectionConfig] = Field(default_factory=dict)
    policy: MCPPolicyConfig = Field(default_factory=MCPPolicyConfig)

    @model_validator(mode="after")
    def _normalize_server_names(self) -> MCPClientConfig:
        normalized: dict[str, MCPServerConnectionConfig] = {}
        for name, config in self.servers.items():
            server_name = normalize_server_name(name)
            if config.namespace is None:
                config.namespace = server_name
            normalized[server_name] = config
        self.servers = normalized
        return self


class MCPConfig(BaseModel):
    """Root MCP config loaded from ``openbench.yaml`` style files."""

    model_config = ConfigDict(extra="forbid")

    server: MCPServerConfig = Field(default_factory=MCPServerConfig)
    servers: dict[str, MCPServerConnectionConfig] = Field(default_factory=dict)
    policy: MCPPolicyConfig = Field(default_factory=MCPPolicyConfig)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> MCPConfig:
        root = data.get("mcp", data)
        return cls.model_validate(expand_env_vars(root or {}))

    @classmethod
    def from_file(cls, path: str | Path) -> MCPConfig:
        config_path = Path(path)
        raw = config_path.read_text(encoding="utf-8")
        if config_path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise ImportError("PyYAML is required to load YAML MCP config") from exc
            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw)
        return cls.from_mapping(data)

    def client_config(self) -> MCPClientConfig:
        return MCPClientConfig(servers=self.servers, policy=self.policy)
