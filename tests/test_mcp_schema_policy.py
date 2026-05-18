"""Tests for OpenBench MCP schema adapters and policy."""

from __future__ import annotations

import pytest

from openbench.mcp.config import MCPConfig
from openbench.mcp.errors import MCPPolicyDeniedError
from openbench.mcp.policy import MCPPolicyEngine, RiskLevel, classify_tool_risk, redact_secrets
from openbench.mcp.schema import (
    mcp_tool_to_openai_schema,
    namespaced_tool_name,
    openbench_schema_to_mcp_tool,
    provider_safe_tool_name,
    split_namespaced_tool,
)


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
    assert classify_tool_risk("append_memory") == RiskLevel.WRITE


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
