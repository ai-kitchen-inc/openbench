"""MCPClient Protocol — minimal surface for MCP-backed skills.

OpenBench skills that wrap an MCP server depend on this Protocol, not on
any specific MCP transport. The deployment is free to bind:

- A subprocess-based stdio MCP client (e.g. spawning
  ``npx @modelcontextprotocol/server-gdrive``).
- An HTTP / SSE MCP client.
- A direct in-process implementation that skips MCP entirely (e.g.
  calling Drive REST APIs directly).
- :class:`MockMCPClient` for tests and skill authoring.

The Protocol is intentionally small: ``call_tool(name, arguments)``
returns a JSON-serializable result, and ``list_tools()`` reports what
the server exposes. Skill ``tools.py`` modules call into this surface;
the heavy MCP wiring (subprocess lifecycle, async bridging, request
multiplexing) lives in transport-specific implementations alongside
this module.

Pillar placement (see ``docs/MENTAL_MODEL.md``): MCP is one of the four
pillars. The Protocol-bound client surface is what skills consume; the
MCP server itself is the external capability provider.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["MCPClient", "MockMCPClient"]


@runtime_checkable
class MCPClient(Protocol):
    """Minimal client surface that MCP-backed skills depend on.

    Implementations are not required to inherit — duck-typing via
    ``runtime_checkable`` is enough. The two methods cover the surface
    needed by the ``drive-explorer`` skill and any future MCP-backed
    skill:

    - :meth:`call_tool` — invoke a named tool on the server, return its
      JSON-decodable result. Tool name and argument schema are defined
      by the MCP server; the skill's wrapper functions know the names.
    - :meth:`list_tools` — discovery, returning the server's advertised
      tool list. Used for diagnostics and skill-side validation; skills
      do not have to call it on every tool invocation.

    Error policy: implementations should raise on transport failure or
    server-side error (rather than returning ``None`` / sentinel values)
    so the agent's tool error path can format a useful message back to
    the user.
    """

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke ``name`` on the MCP server with ``arguments``.

        Returns:
            The tool's JSON-decodable result. Shape is server-defined.
        """
        ...

    def list_tools(self) -> list[dict[str, Any]]:
        """List the tools the bound MCP server advertises.

        Returns:
            One dict per tool with at least ``name`` and ``description``.
        """
        ...


class MockMCPClient:
    """In-memory MCPClient for tests and skill authoring.

    Constructed with a dict mapping tool name to a callable. Each call
    to :meth:`call_tool` invokes the matching callable with the
    arguments dict; missing tool names raise ``KeyError`` so tests
    catch typos in skill wrappers.

    Example:
        >>> client = MockMCPClient({
        ...     "search": lambda args: [{"id": "1", "name": "Q1.pdf"}],
        ... })
        >>> client.call_tool("search", {"query": "Q1"})
        [{'id': '1', 'name': 'Q1.pdf'}]
    """

    def __init__(self, handlers: dict[str, Any]):
        self._handlers = dict(handlers)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._handlers:
            raise KeyError(f"MockMCPClient has no handler for tool {name!r}")
        return self._handlers[name](arguments)

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, "description": ""} for name in sorted(self._handlers)]
