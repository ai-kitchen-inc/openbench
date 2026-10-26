"""FastMCP entrypoint for the custom-function MCP server.

Exposes user-defined Python functions (written by the general-chat API into a
read-only mounted directory) as agent-callable tools. The container this runs
in is the sandbox: non-root, no network, memory/cpu/pids caps.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from typing import Any

from app.service import describe_function, list_functions, run_function

LOGGER = logging.getLogger(__name__)


def _tool_error(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc), "type": type(exc).__name__}


def _run_tool(fn):
    """Run tool logic while keeping third-party prints off MCP stdout."""
    with contextlib.redirect_stdout(sys.stderr):
        return fn()


def build_mcp():
    """Build the FastMCP application."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("Install mcp[cli] to run the custom-function MCP server") from exc

    mcp = FastMCP("custom_function")

    @mcp.tool(
        name="list_functions",
        annotations={
            "title": "List Custom Functions",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def list_functions_tool() -> dict[str, Any]:
        """List the user-defined Python functions available to run."""
        try:
            return _run_tool(list_functions)
        except Exception as exc:
            LOGGER.exception("list_functions failed")
            return _tool_error(exc)

    @mcp.tool(
        name="describe_function",
        annotations={
            "title": "Describe Custom Function",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def describe_function_tool(name: str) -> dict[str, Any]:
        """Show a custom function's source code and metadata."""
        try:
            return _run_tool(lambda: describe_function(name))
        except Exception as exc:
            LOGGER.exception("describe_function failed")
            return _tool_error(exc)

    @mcp.tool(
        name="run_function",
        annotations={
            "title": "Run Custom Function",
            # User-supplied code: not read-only, not guaranteed idempotent.
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def run_function_tool(name: str, kwargs_json: str = "{}") -> dict[str, Any]:
        """Run a user-defined function by name.

        Args:
            name: Function name (see list_functions).
            kwargs_json: JSON object of keyword arguments, e.g. '{"a": 2, "b": 3}'.
        """
        try:
            kwargs = json.loads(kwargs_json) if kwargs_json.strip() else {}
            if not isinstance(kwargs, dict):
                raise ValueError("kwargs_json must be a JSON object")
            return _run_tool(lambda: run_function(name, kwargs))
        except Exception as exc:
            LOGGER.exception("run_function failed")
            return _tool_error(exc)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the custom_function MCP server.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    app = build_mcp()
    if args.transport == "streamable-http":
        app.settings.host = args.host
        app.settings.port = args.port
        app.settings.streamable_http_path = "/mcp"
    elif args.transport == "sse":
        app.settings.host = args.host
        app.settings.port = args.port
    app.run(transport=args.transport)


if __name__ == "__main__":
    main()
