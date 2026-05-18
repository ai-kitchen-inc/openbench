"""MCP integration for OpenBench.

This package is intentionally optional. Importing :mod:`openbench.mcp`
does not require the MCP Python SDK until server/client transports are
constructed.
"""

from openbench.mcp.adapters import MCPToolAdapter, load_mcp_tools
from openbench.mcp.client import MCPClient
from openbench.mcp.config import (
    MCPClientConfig,
    MCPConfig,
    MCPPolicyConfig,
    MCPServerConfig,
    MCPServerConnectionConfig,
)
from openbench.mcp.errors import (
    MCPCapabilityError,
    MCPError,
    MCPPolicyDeniedError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
    MCPTransportError,
)
from openbench.mcp.policy import MCPPolicyEngine, RiskLevel
from openbench.mcp.server import OpenBenchMCPServer

__all__ = [
    "MCPClient",
    "MCPClientConfig",
    "MCPConfig",
    "MCPError",
    "MCPCapabilityError",
    "MCPPolicyConfig",
    "MCPPolicyDeniedError",
    "MCPPolicyEngine",
    "MCPServerConfig",
    "MCPServerConnectionConfig",
    "MCPToolAdapter",
    "MCPToolExecutionError",
    "MCPToolNotFoundError",
    "MCPTransportError",
    "OpenBenchMCPServer",
    "RiskLevel",
    "load_mcp_tools",
]
