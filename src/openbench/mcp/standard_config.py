"""Standard MCP client configuration parsing.

The accepted shape matches common MCP clients:

```
{"mcpServers": {"name": {"command": "docker", "args": ["run", "..."]}}}
```
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from openbench.mcp.config import MCPClientConfig, MCPServerConnectionConfig, TransportName
from openbench.mcp.schema import normalize_server_name


class MCPConfigImportError(ValueError):
    """User-safe MCP configuration import error."""


def parse_standard_mcp_json(raw_json: str) -> MCPClientConfig:
    """Parse a common ``mcpServers`` JSON config without starting servers."""
    try:
        payload = json.loads(raw_json, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise MCPConfigImportError(f"MCP config must be valid JSON: {exc.msg}.") from exc
    except MCPConfigImportError:
        raise

    if not isinstance(payload, dict):
        raise MCPConfigImportError("MCP config must be a JSON object.")
    if "mcpServers" not in payload:
        raise MCPConfigImportError("MCP config must contain a top-level mcpServers object.")

    servers = payload["mcpServers"]
    if not isinstance(servers, dict):
        raise MCPConfigImportError("mcpServers must be an object keyed by server name.")

    normalized_seen: dict[str, str] = {}
    parsed_servers: dict[str, MCPServerConnectionConfig] = {}
    for raw_name, raw_config in servers.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise MCPConfigImportError("Each MCP server name must be a non-empty string.")
        normalized_name = normalize_server_name(raw_name)
        previous = normalized_seen.get(normalized_name)
        if previous is not None:
            raise MCPConfigImportError(
                f"MCP server names {previous!r} and {raw_name!r} normalize to the same name."
            )
        normalized_seen[normalized_name] = raw_name
        parsed_servers[normalized_name] = _parse_server_config(raw_name, raw_config, normalized_name)

    return MCPClientConfig(servers=parsed_servers)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MCPConfigImportError(f"Duplicate JSON key found: {key}.")
        result[key] = value
    return result


def _parse_server_config(
    raw_name: str,
    raw_config: Any,
    normalized_name: str,
) -> MCPServerConnectionConfig:
    if not isinstance(raw_config, dict):
        raise MCPConfigImportError(f"MCP server {raw_name!r} must be an object.")

    command = raw_config.get("command")
    url = raw_config.get("url")
    transport = _transport_for_server(raw_config, bool(command), bool(url), raw_name)

    config: dict[str, Any] = {
        "transport": transport,
        "namespace": normalized_name,
        "enabled": True,
        "allowed": True,
    }

    if command is not None:
        if not isinstance(command, str) or not command.strip():
            raise MCPConfigImportError(f"MCP server {raw_name!r} command must be a non-empty string.")
        config["command"] = command.strip()
    if "args" in raw_config:
        args = raw_config["args"]
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise MCPConfigImportError(f"MCP server {raw_name!r} args must be an array of strings.")
        config["args"] = args
    if "env" in raw_config:
        config["env"] = _string_map(raw_config["env"], raw_name, "env")
    if "cwd" in raw_config:
        cwd = raw_config["cwd"]
        if not isinstance(cwd, str):
            raise MCPConfigImportError(f"MCP server {raw_name!r} cwd must be a string.")
        config["cwd"] = cwd
    if url is not None:
        if not isinstance(url, str) or not url.strip():
            raise MCPConfigImportError(f"MCP server {raw_name!r} url must be a non-empty string.")
        config["url"] = url.strip()
    if "headers" in raw_config:
        config["headers"] = _string_map(raw_config["headers"], raw_name, "headers")

    timeout = raw_config.get("timeout_seconds")
    if timeout is not None:
        config["timeout_seconds"] = timeout
    retries = raw_config.get("retries")
    if retries is not None:
        config["retries"] = retries
    retry_backoff = raw_config.get("retry_backoff_seconds")
    if retry_backoff is not None:
        config["retry_backoff_seconds"] = retry_backoff

    try:
        return MCPServerConnectionConfig.model_validate(config)
    except ValidationError as exc:
        detail = exc.errors()[0].get("msg") if exc.errors() else str(exc)
        raise MCPConfigImportError(f"MCP server {raw_name!r} is invalid: {detail}") from exc
    except ValueError as exc:
        raise MCPConfigImportError(f"MCP server {raw_name!r} is invalid: {exc}") from exc


def _transport_for_server(
    raw_config: dict[str, Any],
    has_command: bool,
    has_url: bool,
    raw_name: str,
) -> TransportName:
    raw_transport = raw_config.get("transport")
    if raw_transport is None:
        if has_command:
            return "stdio"
        if has_url:
            return "streamable-http"
        raise MCPConfigImportError(
            f"MCP server {raw_name!r} must define command or a supported transport/url."
        )
    if raw_transport not in {"stdio", "streamable-http", "sse"}:
        raise MCPConfigImportError(
            f"MCP server {raw_name!r} transport must be stdio, streamable-http, or sse."
        )
    return raw_transport


def _string_map(value: Any, raw_name: str, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MCPConfigImportError(f"MCP server {raw_name!r} {field} must be an object.")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise MCPConfigImportError(
                f"MCP server {raw_name!r} {field} must contain only string keys and string values."
            )
        result[key] = item
    return result
