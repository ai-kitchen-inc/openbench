"""Structured MCP errors used by OpenBench client and server code."""

from __future__ import annotations

from typing import Any


class MCPError(Exception):
    """Base class for OpenBench MCP errors."""

    def __init__(
        self,
        message: str,
        *,
        server: str | None = None,
        tool: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        retry_count: int = 0,
        data: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.server = server
        self.tool = tool
        self.request_id = request_id
        self.correlation_id = correlation_id
        self.retry_count = retry_count
        self.data = data or {}
        self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable error payload."""
        return {
            "type": type(self).__name__,
            "message": self.message,
            "server": self.server,
            "tool": self.tool,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "retry_count": self.retry_count,
            "data": self.data,
        }


class MCPTransportError(MCPError):
    """Transport setup, connection, or request failure."""


class MCPCapabilityError(MCPError):
    """Requested MCP capability is unavailable."""


class MCPToolNotFoundError(MCPError):
    """Requested tool is not known after discovery."""


class MCPPolicyDeniedError(MCPError):
    """Policy denied or gated the requested operation."""


class MCPToolExecutionError(MCPError):
    """Remote or local MCP tool execution failed."""
