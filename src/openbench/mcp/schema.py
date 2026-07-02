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
_PROVIDER_SCHEMA_KEYS = {
    "anyOf",
    "default",
    "description",
    "enum",
    "example",
    "format",
    "items",
    "maxItems",
    "maxLength",
    "maxProperties",
    "maximum",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "nullable",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
}


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
    return _sanitize_provider_json_schema(normalized)


def _sanitize_provider_json_schema(value: Any, *, in_properties: bool = False) -> Any:
    if isinstance(value, list):
        return [
            item
            for item in (_sanitize_provider_json_schema(item) for item in value)
            if item is not None
        ]
    if not isinstance(value, dict):
        return value

    if in_properties:
        return {
            str(key): _sanitize_provider_json_schema(item)
            for key, item in value.items()
            if isinstance(item, dict)
        }

    sanitized: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        if key.startswith("$") or key not in _PROVIDER_SCHEMA_KEYS:
            continue
        if key == "properties":
            sanitized[key] = _sanitize_provider_json_schema(item, in_properties=True)
        elif key == "items":
            if isinstance(item, dict):
                sanitized[key] = _sanitize_provider_json_schema(item)
        elif key == "anyOf":
            if isinstance(item, list):
                any_of = _sanitize_provider_json_schema(item)
                if any_of:
                    sanitized[key] = any_of
        elif key == "required":
            if isinstance(item, list):
                sanitized[key] = [str(entry) for entry in item if isinstance(entry, str)]
        else:
            sanitized[key] = _strict_json_schema_value(item)

    schema_type = sanitized.get("type")
    if isinstance(schema_type, list):
        sanitized["type"] = next((entry for entry in schema_type if isinstance(entry, str)), "object")
    elif schema_type is not None and not isinstance(schema_type, str):
        sanitized.pop("type", None)

    if sanitized.get("type") == "object":
        sanitized.setdefault("properties", {})
        sanitized.setdefault("required", [])

    return sanitized


def _strict_json_schema_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strict_json_schema_value(item)
            for key, item in value.items()
            if not str(key).startswith("$")
        }
    if isinstance(value, list):
        return [_strict_json_schema_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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
