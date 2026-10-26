"""Tests for OpenBench MCP schema adapters and policy."""

from __future__ import annotations

import pytest

from openbench.mcp.config import MCPConfig
from openbench.mcp.errors import MCPPolicyDeniedError
from openbench.mcp.permissions import (
    MCPPermissionContext,
    MCPPermissionRequest,
    MCPPermissionSession,
    parse_permission_response,
    use_mcp_permission_context,
)
from openbench.mcp.policy import MCPPolicyEngine, RiskLevel, classify_tool_risk, redact_secrets
from openbench.mcp.schema import (
    mcp_tool_to_openai_schema,
    namespaced_tool_name,
    openbench_schema_to_mcp_tool,
    provider_safe_tool_name,
    split_namespaced_tool,
)


def test_parse_permission_response_approves_clear_confirmation():
    decision = parse_permission_response("yes, approve")

    assert decision.approved is True
    assert decision.denied is False
    assert decision.ambiguous is False


def test_parse_permission_response_denies_clear_rejection():
    decision = parse_permission_response("no")

    assert decision.approved is False
    assert decision.denied is True
    assert decision.ambiguous is False


def test_parse_permission_response_blocks_unclear_response():
    decision = parse_permission_response("maybe later")

    assert decision.approved is False
    assert decision.denied is False
    assert decision.ambiguous is True


def test_parse_permission_response_blocks_mixed_response():
    decision = parse_permission_response("yes but no")

    assert decision.approved is False
    assert decision.denied is False
    assert decision.ambiguous is True


def test_request_scoped_permission_provider_overrides_session_provider():
    request = MCPPermissionRequest(
        tool_name="openbench.distinct_values",
        purpose="Distinct values",
        arguments={"column": "region"},
        risk=RiskLevel.READ,
        action="Call test tool.",
    )
    session = MCPPermissionSession(lambda _request: "no")
    context = MCPPermissionContext(lambda _request: "yes")

    with use_mcp_permission_context(context):
        decision = session.request(request)

    assert decision.approved is True


def test_request_scoped_permission_cache_does_not_leak_between_contexts():
    request = MCPPermissionRequest(
        tool_name="openbench.distinct_values",
        purpose="Distinct values",
        arguments={"column": "region"},
        risk=RiskLevel.READ,
        action="Call test tool.",
    )
    session = MCPPermissionSession()
    with use_mcp_permission_context(MCPPermissionContext(lambda _request: "yes")):
        approved = session.request(request)
    with use_mcp_permission_context(MCPPermissionContext(lambda _request: "no")):
        denied = session.request(request)

    assert approved.approved is True
    assert denied.denied is True


def test_request_scoped_permission_cache_prompts_once_for_identical_action():
    request = MCPPermissionRequest(
        tool_name="openbench.distinct_values",
        purpose="Distinct values",
        arguments={"column": "region"},
        risk=RiskLevel.READ,
        action="Call test tool.",
    )
    calls = []

    def provider(seen_request):
        calls.append(seen_request)
        return "yes"

    session = MCPPermissionSession()
    with use_mcp_permission_context(MCPPermissionContext(provider)):
        first = session.request(request)
        second = session.request(request)

    assert first.approved is True
    assert second.approved is True
    assert len(calls) == 1


def test_openai_function_schema_converts_to_mcp_tool():
    schema = {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Read a PDF",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }

    tool = openbench_schema_to_mcp_tool(
        schema, fallback_name="fallback", source_skill="pdf-tools"
    )

    assert tool["name"] == "read_pdf"
    assert tool["inputSchema"]["required"] == ["path"]
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["_meta"]["dev.openbench/sourceSkill"] == "pdf-tools"


def test_flat_function_schema_converts_to_mcp_tool():
    schema = {
        "name": "read_memory",
        "description": "Read memory",
        "parameters": {"properties": {"key": {"type": "string"}}},
    }

    tool = openbench_schema_to_mcp_tool(schema, fallback_name="read_memory")

    assert tool["name"] == "read_memory"
    assert tool["inputSchema"]["type"] == "object"
    assert tool["inputSchema"]["required"] == []


def test_mcp_tool_converts_to_provider_safe_schema():
    tool = {
        "name": "search",
        "description": "Search things",
        "inputSchema": {"type": "object", "properties": {}},
    }

    schema = mcp_tool_to_openai_schema(tool, namespaced_name="github.search")

    assert schema["function"]["name"] == "github_search"
    assert schema["_meta"]["dev.openbench/canonicalName"] == "github.search"


def test_mcp_tool_provider_schema_strips_json_schema_dialect_keys():
    tool = {
        "name": "read_text_file",
        "description": "Read a file",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "path": {
                    "$comment": "Filesystem server metadata",
                    "type": "string",
                }
            },
            "required": ["path"],
        },
    }

    schema = mcp_tool_to_openai_schema(tool, namespaced_name="filesystem.read_text_file")

    parameters = schema["function"]["parameters"]
    assert "$schema" not in parameters
    assert "$comment" not in parameters["properties"]["path"]
    assert parameters["properties"]["path"]["type"] == "string"


def test_mcp_tool_provider_schema_strips_unsupported_json_schema_keywords():
    original_schema = {
        "type": "object",
        "properties": {
            "data": {
                "description": "MIME data map",
                "type": "object",
                "propertyNames": {"type": "string"},
                "patternProperties": {"^text/": {"type": "string"}},
                "additionalProperties": {"type": "string"},
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "if": {"const": "x"}}},
                    "required": ["name"],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": ["data"],
        "dependentRequired": {"data": ["items"]},
    }
    tool = {
        "name": "browser_drop",
        "description": "Drop files or MIME-typed data",
        "inputSchema": original_schema,
    }

    schema = mcp_tool_to_openai_schema(tool, namespaced_name="playwright.browser_drop")

    parameters = schema["function"]["parameters"]
    data_schema = parameters["properties"]["data"]
    nested_item_schema = parameters["properties"]["items"]["items"]
    assert "propertyNames" not in data_schema
    assert "patternProperties" not in data_schema
    assert "additionalProperties" not in data_schema
    assert "dependentRequired" not in parameters
    assert "unevaluatedProperties" not in nested_item_schema
    assert "additionalProperties" not in nested_item_schema
    assert "if" not in nested_item_schema["properties"]["name"]
    assert original_schema["properties"]["data"]["propertyNames"] == {"type": "string"}
    assert original_schema["properties"]["data"]["additionalProperties"] == {"type": "string"}


def test_mcp_tool_provider_schema_strips_additional_properties_recursively():
    tool = {
        "name": "browser_fill_form",
        "description": "Fill multiple form fields",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "value": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                        },
                        "required": ["target"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["fields"],
            "additionalProperties": False,
        },
    }

    schema = mcp_tool_to_openai_schema(tool, namespaced_name="playwright.browser_fill_form")

    parameters = schema["function"]["parameters"]
    item_schema = parameters["properties"]["fields"]["items"]
    value_schema = item_schema["properties"]["value"]
    assert "additionalProperties" not in parameters
    assert "additionalProperties" not in item_schema
    assert "additionalProperties" not in value_schema


def test_namespaced_tool_helpers():
    assert namespaced_tool_name("GitHub Official", "search/code") == "github-official.search_code"
    assert split_namespaced_tool("github.search") == ("github", "search")
    assert provider_safe_tool_name("github.search-code") == "github_search_code"
    with pytest.raises(ValueError):
        split_namespaced_tool("missing_namespace")


def test_default_risk_classification():
    assert classify_tool_risk("read_pdf") == RiskLevel.READ
    assert classify_tool_risk("export_to_excel") == RiskLevel.ARTIFACT_WRITE
    assert classify_tool_risk("web_search") == RiskLevel.EXTERNAL_NETWORK
    assert classify_tool_risk("fetch_url") == RiskLevel.EXTERNAL_NETWORK
    assert classify_tool_risk("append_memory") == RiskLevel.WRITE
    assert classify_tool_risk("index_images") == RiskLevel.WRITE
    assert classify_tool_risk("rebuild_index") == RiskLevel.DESTRUCTIVE
    assert classify_tool_risk("remove_image") == RiskLevel.DESTRUCTIVE
    assert classify_tool_risk("search_similar_images") == RiskLevel.READ


def test_policy_denies_remote_by_default():
    policy = MCPPolicyEngine()
    decision = policy.authorize(server="remote", tool="read_pdf", remote=True)
    assert decision.allowed is False
    assert "not explicitly allowed" in decision.reason


def test_policy_requires_approval_for_risk():
    policy = MCPPolicyEngine(
        allowed_servers=["openbench"],
        require_approval_for_risks=["artifact_write"],
    )
    decision = policy.authorize(server="openbench", tool="export_to_excel")
    assert decision.allowed is False
    assert decision.approval_required is True
    with pytest.raises(MCPPolicyDeniedError):
        policy.enforce(server="openbench", tool="export_to_excel")

    approved = policy.authorize(
        server="openbench",
        tool="export_to_excel",
        approved=True,
    )
    assert approved.allowed is True


def test_redact_secrets():
    value = {
        "Authorization": "Bearer abc123",
        "nested": {"api_key": "secret"},
        "text": "token='abc'",
    }
    redacted = redact_secrets(value)
    assert redacted["Authorization"] == "***REDACTED***"
    assert redacted["nested"]["api_key"] == "***REDACTED***"
    assert "***REDACTED***" in redacted["text"]


def test_config_expands_environment(monkeypatch):
    monkeypatch.setenv("OPENBENCH_MCP_TEST_URL", "http://127.0.0.1:9999/mcp")
    config = MCPConfig.from_mapping(
        {
            "mcp": {
                "servers": {
                    "local": {
                        "transport": "streamable-http",
                        "url": "${OPENBENCH_MCP_TEST_URL}",
                        "allowed": True,
                    }
                }
            }
        }
    )
    assert config.servers["local"].url == "http://127.0.0.1:9999/mcp"
