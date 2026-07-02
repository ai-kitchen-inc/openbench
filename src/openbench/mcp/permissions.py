"""Runtime permission prompts for MCP tool execution."""

from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from openbench.mcp.policy import RiskLevel, redact_secrets

PermissionStatus = Literal["approved", "denied", "ambiguous"]

_APPROVAL_WORDS = {
    "approve",
    "approved",
    "allow",
    "allowed",
    "confirm",
    "confirmed",
    "ok",
    "okay",
    "proceed",
    "yes",
    "y",
}
_DENIAL_WORDS = {
    "cancel",
    "deny",
    "denied",
    "disallow",
    "no",
    "nope",
    "reject",
    "rejected",
    "stop",
    "n",
}


@dataclass(frozen=True)
class MCPPermissionRequest:
    """User-facing request for permission to execute one MCP tool action."""

    tool_name: str
    purpose: str
    arguments: dict[str, Any]
    risk: RiskLevel
    action: str

    @property
    def access_kind(self) -> str:
        """Return a concise description of the access this tool may perform."""
        labels = {
            RiskLevel.READ: "read data",
            RiskLevel.WRITE: "modify data",
            RiskLevel.ARTIFACT_WRITE: "create or modify artifacts",
            RiskLevel.EXTERNAL_NETWORK: "contact an external service",
            RiskLevel.DESTRUCTIVE: "perform a destructive action",
        }
        return labels.get(self.risk, "read data")

    def message(self) -> str:
        """Build a concise permission prompt for host runtimes."""
        return (
            f"Allow MCP tool '{self.tool_name}'?\n"
            f"Purpose: {self.purpose or 'No description provided.'}\n"
            f"Action: {self.action}\n"
            f"Access: may {self.access_kind}."
        )


@dataclass(frozen=True)
class MCPPermissionDecision:
    """Parsed permission decision for an MCP action."""

    status: PermissionStatus
    raw_response: str | None = None
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    @property
    def denied(self) -> bool:
        return self.status == "denied"

    @property
    def ambiguous(self) -> bool:
        return self.status == "ambiguous"


PermissionProvider = Callable[
    [MCPPermissionRequest], str | bool | MCPPermissionDecision | None
]


class MCPPermissionContext:
    """Request-scoped MCP permission provider and decision cache."""

    def __init__(self, provider: PermissionProvider):
        self.provider = provider
        self._cache: dict[str, MCPPermissionDecision] = {}
        self._lock = threading.Lock()

    def request(self, request: MCPPermissionRequest) -> MCPPermissionDecision:
        key = MCPPermissionSession.cache_key(request)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        try:
            decision = parse_permission_response(self.provider(request))
        except Exception as exc:
            decision = MCPPermissionDecision(
                "ambiguous",
                reason=f"Permission provider failed: {exc}",
            )

        with self._lock:
            self._cache.setdefault(key, decision)
            return self._cache[key]


_CURRENT_PERMISSION_CONTEXT: ContextVar[MCPPermissionContext | None] = ContextVar(
    "openbench_mcp_permission_context",
    default=None,
)


@contextmanager
def use_mcp_permission_context(
    context: MCPPermissionContext | None,
) -> Iterator[None]:
    """Activate an MCP permission context for the current execution flow."""
    if context is None:
        yield
        return
    token = _CURRENT_PERMISSION_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_PERMISSION_CONTEXT.reset(token)


def parse_permission_response(
    response: str | bool | MCPPermissionDecision | None,
) -> MCPPermissionDecision:
    """Parse a host/user response into a conservative permission decision."""
    if isinstance(response, MCPPermissionDecision):
        return response
    if response is True:
        return MCPPermissionDecision(
            "approved",
            raw_response="true",
            reason="Programmatic approval",
        )
    if response is False:
        return MCPPermissionDecision(
            "denied",
            raw_response="false",
            reason="Programmatic denial",
        )
    if response is None:
        return MCPPermissionDecision("ambiguous", reason="No permission response")

    raw = str(response).strip()
    if not raw:
        return MCPPermissionDecision(
            "ambiguous",
            raw_response=raw,
            reason="Empty response",
        )

    words = set(re.findall(r"[a-zA-Z]+", raw.lower()))
    approvals = words & _APPROVAL_WORDS
    denials = words & _DENIAL_WORDS
    if approvals and not denials:
        return MCPPermissionDecision(
            "approved",
            raw_response=raw,
            reason="Explicit approval",
        )
    if denials and not approvals:
        return MCPPermissionDecision(
            "denied",
            raw_response=raw,
            reason="Explicit denial",
        )
    if approvals and denials:
        return MCPPermissionDecision(
            "ambiguous",
            raw_response=raw,
            reason="Response contains both approval and denial",
        )
    return MCPPermissionDecision(
        "ambiguous",
        raw_response=raw,
        reason="Response did not clearly approve",
    )


class MCPPermissionSession:
    """Thread-safe permission prompt cache for one user task/session."""

    def __init__(self, provider: PermissionProvider | None = None):
        self.provider = provider
        self._cache: dict[str, MCPPermissionDecision] = {}
        self._lock = threading.Lock()

    def request(self, request: MCPPermissionRequest) -> MCPPermissionDecision:
        """Return cached or newly requested permission for an MCP action."""
        active_context = _CURRENT_PERMISSION_CONTEXT.get()
        if active_context is not None:
            return active_context.request(request)

        key = self.cache_key(request)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        if self.provider is None:
            decision = MCPPermissionDecision(
                "ambiguous",
                reason="No MCP permission provider configured",
            )
        else:
            try:
                decision = parse_permission_response(self.provider(request))
            except Exception as exc:
                decision = MCPPermissionDecision(
                    "ambiguous",
                    reason=f"Permission provider failed: {exc}",
                )

        with self._lock:
            self._cache.setdefault(key, decision)
            return self._cache[key]

    @staticmethod
    def cache_key(request: MCPPermissionRequest) -> str:
        payload = {
            "tool_name": request.tool_name,
            "arguments": request.arguments,
            "risk": request.risk.value,
            "action": request.action,
        }
        return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def redacted_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return secret-redacted arguments suitable for prompting and cache keys."""
    redacted = redact_secrets(arguments)
    return redacted if isinstance(redacted, dict) else {}
