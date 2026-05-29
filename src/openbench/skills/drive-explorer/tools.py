"""Tools for the drive-explorer skill.

Thin wrappers that translate the agent's tool calls into MCP
``call_tool`` invocations against a bound MCPClient. The actual Drive
operations run inside the MCP server process; this module never imports
any Drive SDK and never speaks to Google directly.

Binding works the same as :mod:`openbench.skills.memory-scratchpad.tools`
— ``SkillRegistry.bind(mcp_client=...)`` calls the module-level
:func:`bind` below, which stashes the client in a module-level slot
the wrapper functions read from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.integrations.mcp import MCPClient


_client: MCPClient | None = None


def bind(mcp_client: MCPClient | None = None, **_: object) -> None:
    """Inject the MCPClient the agent was configured with.

    Called by :meth:`SkillRegistry.bind` during :class:`BaseAgent`
    construction. Extra keyword arguments (e.g. ``scratchpad``) are
    ignored so the bind contract stays uniform across skills.
    """
    global _client
    _client = mcp_client


def _require_client() -> MCPClient:
    if _client is None:
        raise RuntimeError(
            "drive-explorer skill is not bound. Pass mcp_client= to "
            "BaseAgent (an MCPClient instance wrapping a Drive MCP "
            "server). See references/mcp-server-setup.md for the binding "
            "pattern and the reference server."
        )
    return _client


# ---------------------------------------------------------------------------
# Tools (convention: FOO_SCHEMA + foo() pair discovered by SkillRegistry)
# ---------------------------------------------------------------------------


DRIVE_SEARCH_SCHEMA: dict = {
    "name": "drive_search",
    "description": (
        "Search the user's Google Drive for files matching a keyword "
        "query. Returns up to max_results entries with id, name, "
        "mimeType, and modifiedTime. Use 1-3 keyword terms; broaden "
        "the query if the first attempt returns zero results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword query (1-3 short terms work best).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 10).",
                "default": 10,
            },
        },
        "required": ["query"],
    },
}


def drive_search(query: str, max_results: int = 10) -> Any:
    """Search the user's Drive via the bound MCP server."""
    return _require_client().call_tool(
        "search",
        {"query": query, "max_results": max_results},
    )


DRIVE_READ_FILE_SCHEMA: dict = {
    "name": "drive_read_file",
    "description": (
        "Fetch a file's content by its Drive file id. Use after "
        "drive_search has identified the right file. Large files may "
        "be truncated server-side — check the result for a "
        "'truncated' flag if present."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Drive file id (from a prior drive_search result).",
            },
        },
        "required": ["file_id"],
    },
}


def drive_read_file(file_id: str) -> Any:
    """Fetch a file's content via the bound MCP server."""
    return _require_client().call_tool("read_file", {"file_id": file_id})


DRIVE_LIST_RECENT_SCHEMA: dict = {
    "name": "drive_list_recent",
    "description": (
        "List recently modified files in the user's Drive. Use this "
        "for 'what changed recently?' style questions, or to give the "
        "agent context about what the user has been working on."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 10).",
                "default": 10,
            },
        },
        "required": [],
    },
}


def drive_list_recent(max_results: int = 10) -> Any:
    """List recently modified files via the bound MCP server."""
    return _require_client().call_tool("list_recent", {"max_results": max_results})


DRIVE_GET_METADATA_SCHEMA: dict = {
    "name": "drive_get_metadata",
    "description": (
        "Read a file's metadata (name, owner, modified time, size) "
        "without downloading its content. Prefer this over "
        "drive_read_file when the user's question is about *when* or "
        "*by whom* a file changed, not its contents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Drive file id.",
            },
        },
        "required": ["file_id"],
    },
}


def drive_get_metadata(file_id: str) -> Any:
    """Get file metadata via the bound MCP server."""
    return _require_client().call_tool("get_metadata", {"file_id": file_id})
