# MCP Server Setup for drive-explorer

This skill expects an :class:`openbench.integrations.mcp.MCPClient`
instance bound to it at agent construction. The skill is transport-
and server-agnostic — any client that satisfies the MCPClient Protocol
is acceptable.

## Reference server

The reference target is Anthropic's
[`@modelcontextprotocol/server-gdrive`](https://www.npmjs.com/package/@modelcontextprotocol/server-gdrive).
Spawn it as a subprocess and bridge stdio into an MCPClient impl.
The server expects Google credentials in environment variables.

## Tools the skill calls

The skill's wrapper functions call these MCP tool names (matching the
reference server). If your bound MCPClient targets a different server,
either rename the calls or wrap the server with a translation layer.

| Skill wrapper | MCP tool name | Arguments |
|---|---|---|
| `drive_search` | `search` | `{"query": str, "max_results": int}` |
| `drive_read_file` | `read_file` | `{"file_id": str}` |
| `drive_list_recent` | `list_recent` | `{"max_results": int}` |
| `drive_get_metadata` | `get_metadata` | `{"file_id": str}` |

## Binding the client

```python
from openbench.integrations.mcp import MCPClient
from openbench.intelligence.base import BaseAgent

client: MCPClient = your_mcp_client_factory(...)

agent = BaseAgent(
    goal="...",
    persona="soul/",
    skills=["drive-explorer"],
    mcp_client=client,
)
```

The `mcp_client` keyword is forwarded to the skill's `bind(**kwargs)`
hook by ``SkillRegistry.bind()``. Skills without an MCP dependency
ignore it.

## Auth

For per-request user OAuth (the lci-mini pattern), the simplest shape
is one MCPClient instance per request, constructed inside the
request scope using the caller's :class:`DriveToken`. The MCP server
subprocess can be reused if your client implementation supports
multiplexing; otherwise a fresh subprocess per request is acceptable
at low request rates.

For single-tenant or service-account deployments, one long-lived
MCPClient at process startup is the right default.

## Testing

Use :class:`openbench.integrations.mcp.MockMCPClient` to author skill
behavior without a running MCP server. Each test can declare its own
handler set:

```python
from openbench.integrations.mcp import MockMCPClient

client = MockMCPClient({
    "search": lambda args: [{"id": "1", "name": "Q1.pdf"}],
    "read_file": lambda args: {"id": "1", "content": "..."},
})
```
