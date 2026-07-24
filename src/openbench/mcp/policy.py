"""Security policy for OpenBench MCP tool access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from openbench.mcp.errors import MCPPolicyDeniedError
from openbench.mcp.observability import get_correlation_id, metrics


class RiskLevel(str, Enum):
    """Known MCP tool risk classes."""

    READ = "read"
    WRITE = "write"
    ARTIFACT_WRITE = "artifact_write"
    EXTERNAL_NETWORK = "external_network"
    DESTRUCTIVE = "destructive"


READ_TOOLS = {
    "extract_file_context",
    "read_csv_file",
    "read_excel_file",
    "list_excel_sheets",
    "get_column_profile",
    "pdf_metadata",
    "read_pdf",
    "read_pdf_page",
    "extract_pdf_tables",
    "filter_records",
    "sort_records",
    "group_and_aggregate",
    "distinct_values",
    "top_n_records",
    "extract_metadata",
    "aggregate_data",
    "load_dashboard_memory",
    "read_memory",
    "list_memory_keys",
    "list_index_stats",
    "search_similar_images",
    "count_objects_with_sam3",
    "service_info",
}

WRITE_TOOLS = {
    "save_column_profile",
    "update_column_profile",
    "write_memory",
    "append_memory",
    "index_images",
}

ARTIFACT_TOOLS = {
    "export_to_excel",
    "export_multi_sheet_excel",
    "merge_pdfs",
    "split_pdf",
    "generate_pdf",
    "generate_dashboard",
}

NETWORK_TOOLS = {"web_search", "web_search_multi", "fetch_url"}

DESTRUCTIVE_TOOLS = {
    "rebuild_index",
    "remove_image",
}


def classify_tool_risk(tool_name: str) -> RiskLevel:
    """Return the default risk classification for a tool name."""
    short_name = tool_name.rsplit(".", 1)[-1]
    if short_name in NETWORK_TOOLS:
        return RiskLevel.EXTERNAL_NETWORK
    if short_name in DESTRUCTIVE_TOOLS:
        return RiskLevel.DESTRUCTIVE
    if short_name in ARTIFACT_TOOLS:
        return RiskLevel.ARTIFACT_WRITE
    if short_name in WRITE_TOOLS:
        return RiskLevel.WRITE
    if short_name in READ_TOOLS:
        return RiskLevel.READ
    return RiskLevel.READ


@dataclass(frozen=True)
class PolicyDecision:
    """Result of an MCP policy check."""

    allowed: bool
    reason: str
    risk: RiskLevel
    approval_required: bool = False


class MCPPolicyEngine:
    """Authorize server/tool access before execution."""

    def __init__(
        self,
        *,
        allowed_servers: list[str] | None = None,
        denied_servers: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        require_approval_for_risks: list[str] | None = None,
        allow_remote_servers: bool = False,
        max_timeout_seconds: float = 30.0,
        max_response_chars: int = 200_000,
    ):
        self.allowed_servers = set(allowed_servers or [])
        self.denied_servers = set(denied_servers or [])
        self.allowed_tools = set(allowed_tools or [])
        self.denied_tools = set(denied_tools or [])
        self.require_approval_for_risks = {
            RiskLevel(r) for r in (require_approval_for_risks or [])
        }
        self.allow_remote_servers = allow_remote_servers
        self.max_timeout_seconds = max_timeout_seconds
        self.max_response_chars = max_response_chars

    def authorize(
        self,
        *,
        server: str,
        tool: str,
        risk: RiskLevel | str | None = None,
        remote: bool = False,
        approved: bool = False,
        timeout_seconds: float | None = None,
    ) -> PolicyDecision:
        """Return a policy decision for a tool call."""
        risk_level = RiskLevel(risk) if risk else classify_tool_risk(tool)
        namespaced = f"{server}.{tool}" if "." not in tool else tool

        if server in self.denied_servers:
            return self._deny(f"server {server!r} is denied", risk_level)
        if namespaced in self.denied_tools or tool in self.denied_tools:
            return self._deny(f"tool {namespaced!r} is denied", risk_level)
        if remote and not self.allow_remote_servers and server not in self.allowed_servers:
            return self._deny(
                f"remote server {server!r} is not explicitly allowed", risk_level
            )
        if self.allowed_servers and server not in self.allowed_servers:
            return self._deny(f"server {server!r} is not allowed", risk_level)
        if self.allowed_tools and namespaced not in self.allowed_tools and tool not in self.allowed_tools:
            return self._deny(f"tool {namespaced!r} is not allowed", risk_level)
        if timeout_seconds and timeout_seconds > self.max_timeout_seconds:
            return self._deny(
                f"timeout {timeout_seconds}s exceeds maximum {self.max_timeout_seconds}s",
                risk_level,
            )
        if risk_level in self.require_approval_for_risks and not approved:
            metrics.inc("policy_denials_total")
            return PolicyDecision(
                allowed=False,
                reason=f"tool {namespaced!r} requires approval for risk {risk_level.value}",
                risk=risk_level,
                approval_required=True,
            )
        return PolicyDecision(True, "allowed", risk_level)

    def enforce(self, **kwargs: Any) -> PolicyDecision:
        """Authorize or raise :class:`MCPPolicyDeniedError`."""
        decision = self.authorize(**kwargs)
        if not decision.allowed:
            metrics.inc("policy_denials_total")
            raise MCPPolicyDeniedError(
                decision.reason,
                server=kwargs.get("server"),
                tool=kwargs.get("tool"),
                correlation_id=get_correlation_id(),
                data={
                    "risk": decision.risk.value,
                    "approval_required": decision.approval_required,
                },
            )
        return decision

    @staticmethod
    def _deny(reason: str, risk: RiskLevel) -> PolicyDecision:
        metrics.inc("policy_denials_total")
        return PolicyDecision(False, reason, risk)


_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s,}]+"),
    re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+"),
    re.compile(r"(?i)(token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+"),
]


def redact_secrets(value: Any) -> Any:
    """Redact likely secrets from nested values."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(
                part in key.lower()
                for part in ("authorization", "token", "secret", "api_key", "password")
            ):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub(r"\1***REDACTED***", out)
        return out
    return value
