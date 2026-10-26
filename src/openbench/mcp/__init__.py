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
from openbench.mcp.permissions import (
    MCPPermissionContext,
    MCPPermissionDecision,
    MCPPermissionRequest,
    MCPPermissionSession,
    PermissionProvider,
    parse_permission_response,
    use_mcp_permission_context,
)
from openbench.mcp.policy import MCPPolicyEngine, RiskLevel
from openbench.mcp.server import OpenBenchMCPServer
from openbench.mcp.standard_config import MCPConfigImportError, parse_standard_mcp_json
from openbench.mcp.toolhive import (
    ToolHiveError,
    ToolHiveRegistryServer,
    ToolHiveService,
    ToolHiveStatus,
    ToolHiveWorkload,
    detect_toolhive_transport,
    rewrite_toolhive_url,
    toolhive_workload_to_mcp_config,
)

__all__ = [
    "MCPClient",
    "MCPClientConfig",
    "MCPConfig",
    "MCPError",
    "MCPCapabilityError",
    "MCPPolicyConfig",
    "MCPPolicyDeniedError",
    "MCPPolicyEngine",
    "MCPPermissionDecision",
    "MCPPermissionContext",
    "MCPPermissionRequest",
    "MCPPermissionSession",
    "MCPServerConfig",
    "MCPServerConnectionConfig",
    "MCPToolAdapter",
    "MCPToolExecutionError",
    "MCPToolNotFoundError",
    "MCPTransportError",
    "OpenBenchMCPServer",
    "PermissionProvider",
    "RiskLevel",
    "load_mcp_tools",
    "parse_permission_response",
    "use_mcp_permission_context",
    "MCPConfigImportError",
    "parse_standard_mcp_json",
    "ToolHiveError",
    "ToolHiveRegistryServer",
    "ToolHiveService",
    "ToolHiveStatus",
    "ToolHiveWorkload",
    "detect_toolhive_transport",
    "rewrite_toolhive_url",
    "toolhive_workload_to_mcp_config",
]
