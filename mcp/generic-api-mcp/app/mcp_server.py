"""FastMCP entrypoint for generic authenticated API access."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from typing import Any

from app.service import QueryParamValue, get_service

LOGGER = logging.getLogger(__name__)


def _run_tool(fn):
    """Run tool logic while keeping third-party prints off MCP stdout."""
    with contextlib.redirect_stdout(sys.stderr):
        return fn()


def build_mcp():
    """Build the FastMCP application."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("Install mcp[cli] to run the generic API MCP server") from exc

    mcp = FastMCP("generic_api_mcp")

    @mcp.tool(
        name="fetch_generic_api_data",
        annotations={
            "title": "Fetch Generic API Data",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fetch_generic_api_data(
        endpoint_url: str,
        query_params: dict[str, QueryParamValue] | None = None,
    ) -> dict[str, Any]:
        """Fetch data from the provided API endpoint."""
        try:
            return _run_tool(
                lambda: get_service().fetch_generic_api_data(
                    endpoint_url=endpoint_url,
                    query_params=query_params,
                )
            )
        except Exception as exc:
            LOGGER.exception("fetch_generic_api_data failed")
            raise exc

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the generic_api_mcp server.")
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
