"""Schema adapters between OpenBench function tools and MCP tools."""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from openbench.mcp.policy import RiskLevel, classify_tool_risk

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_PROVIDER_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def normalize_server_name(name: str) -> str:
    """Normalize a server namespace while preserving readability."""
    cleaned = _NAME_RE.sub("-", name.strip().lower()).strip("-_")
    return cleaned or "server"


def normalize_tool_name(name: str) -> str:
    """Normalize an MCP tool name without a server namespace."""
    cleaned = _NAME_RE.sub("_", name.strip()).strip("_-")
    return cleaned or "tool"


def namespaced_tool_name(server: str, tool: str) -> str:
    """Return OpenBench's canonical namespaced MCP tool name."""
    return f"{normalize_server_name(server)}.{normalize_tool_name(tool)}"


def split_namespaced_tool(name: str) -> tuple[str, str]:
    """Split ``server.tool`` into ``(server, tool)``."""
    if "." not in name:
        raise ValueError(f"MCP tool name must be namespaced as server.tool: {name!r}")
    server, tool = name.split(".", 1)
    if not server or not tool:
        raise ValueError(f"Invalid namespaced MCP tool name: {name!r}")
    return server, tool


def provider_safe_tool_name(name: str) -> str:
    """Return a reversible-ish provider-safe tool name.

    Some LLM providers reject dots in function names, so OpenBench keeps
    canonical names in client APIs and uses this adapter at provider edges.
    """
    return _PROVIDER_NAME_RE.sub("_", name).strip("_") or "tool"


def _unwrap_function_schema(schema: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
        return copy.deepcopy(schema["function"])
    return copy.deepcopy(schema) | {"name": schema.get("name", fallback_name)}


def normalize_json_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an object JSON Schema for MCP tool inputs."""
    normalized = copy.deepcopy(schema or {})
    if normalized.get("type") is None:
        normalized["type"] = "object"
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
    if "required" in normalized and normalized["required"] is None:
        normalized["required"] = []
    return normalized


def normalize_provider_json_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an MCP JSON Schema for LLM provider function declarations.

    MCP servers often expose draft JSON Schema metadata such as ``$schema``.
    Provider SDKs such as Gemini validate against a narrower schema model and
    reject those extension keys, so provider-facing schemas must be cleaned
    without mutating the original MCP discovery payload.
    """
    normalized = normalize_json_schema(schema)
    return _strip_json_schema_dialect_keys(normalized)


def _strip_json_schema_dialect_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_json_schema_dialect_keys(item)
            for key, item in value.items()
            if not str(key).startswith("$")
        }
    if isinstance(value, list):
        return [_strip_json_schema_dialect_keys(item) for item in value]
    return value


def openbench_schema_to_mcp_tool(
    schema: dict[str, Any],
    *,
    fallback_name: str,
    source_skill: str | None = None,
    risk: RiskLevel | str | None = None,
) -> dict[str, Any]:
    """Convert an OpenBench/OpenAI-style function schema to an MCP tool."""
    func = _unwrap_function_schema(schema, fallback_name)
    tool_name = normalize_tool_name(str(func.get("name") or fallback_name))
    input_schema = normalize_json_schema(func.get("parameters"))
    risk_level = RiskLevel(risk) if risk else classify_tool_risk(tool_name)
    annotations = {
        "readOnlyHint": risk_level == RiskLevel.READ,
        "destructiveHint": risk_level == RiskLevel.DESTRUCTIVE,
        "idempotentHint": risk_level == RiskLevel.READ,
        "openWorldHint": risk_level == RiskLevel.EXTERNAL_NETWORK,
    }
    meta: dict[str, Any] = {
        "dev.openbench/risk": risk_level.value,
    }
    if source_skill:
        meta["dev.openbench/sourceSkill"] = source_skill
    return {
        "name": tool_name,
        "title": str(func.get("title") or tool_name.replace("_", " ").title()),
        "description": str(func.get("description") or ""),
        "inputSchema": input_schema,
        "annotations": annotations,
        "_meta": meta,
    }


def mcp_tool_to_openai_schema(tool: dict[str, Any], *, namespaced_name: str | None = None) -> dict:
    """Convert an MCP tool definition to OpenAI/Gemini function schema."""
    name = namespaced_name or str(tool["name"])
    return {
        "type": "function",
        "function": {
            "name": provider_safe_tool_name(name),
            "description": tool.get("description", ""),
            "parameters": normalize_provider_json_schema(tool.get("inputSchema")),
        },
        "_meta": {
            "dev.openbench/canonicalName": name,
            **dict(tool.get("_meta") or {}),
        },
    }


def sanitize_json_value(value: Any) -> Any:
    """Return a strict-JSON-compatible value."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json_value(v) for v in value]
    return value


def tool_result_to_text(value: Any) -> str:
    """Serialize a tool result for MCP text fallback content."""
    sanitized = sanitize_json_value(value)
    if isinstance(sanitized, str):
        return sanitized
    return json.dumps(sanitized, default=str, allow_nan=False)


def is_error_result(value: Any) -> bool:
    """Return True for OpenBench's conventional ``{"error": ...}`` result."""
    return isinstance(value, dict) and "error" in value
