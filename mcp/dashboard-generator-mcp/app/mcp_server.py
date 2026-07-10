"""FastMCP entrypoint for the dashboard-generator MCP server."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from typing import Any

from app.service import get_service

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
        raise ImportError("Install mcp[cli] to run the dashboard-generator MCP server") from exc

    mcp = FastMCP("dashboard_generator_mcp")

    @mcp.tool(
        name="generate_dashboard",
        annotations={
            "title": "Generate Dashboard",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def generate_dashboard(
        view_model: dict[str, Any],
        filename: str | None = None,
        output_dir: str | None = None,
        template_path: str | None = None,
        template_text: str | None = None,
        template_format: str | None = None,
    ) -> dict[str, Any]:
        """Render a declarative dashboard ViewModel as an HTML/A2UI artifact."""
        try:
            return _run_tool(
                lambda: get_service().generate_dashboard(
                    view_model=view_model,
                    filename=filename,
                    output_dir=output_dir,
                    template_path=template_path,
                    template_text=template_text,
                    template_format=template_format,
                )
            )
        except Exception as exc:
            LOGGER.exception("generate_dashboard failed")
            return _tool_error(exc)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dashboard_generator_mcp server.")
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
