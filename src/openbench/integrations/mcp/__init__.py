"""MCP (Model Context Protocol) client abstractions and default impls.

This package is the MCP pillar's home in OpenBench (see
``docs/MENTAL_MODEL.md``). It contains:

- A minimal :class:`MCPClient` Protocol — the surface that
  MCP-backed skills depend on.
- :class:`MockMCPClient` — in-memory default for tests and skill
  authoring without a live server.

Real transport-specific clients (stdio subprocess, HTTP, SSE) live in
their own modules so the Protocol stays dependency-free. Add new ones
alongside as you need them; the Protocol is the public contract.
"""

from openbench.integrations.mcp.client import MCPClient, MockMCPClient

__all__ = ["MCPClient", "MockMCPClient"]
