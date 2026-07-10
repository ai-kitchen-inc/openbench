"""FastMCP entrypoint for the aggregate-data MCP server."""

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
        raise ImportError("Install mcp[cli] to run the aggregate-data MCP server") from exc

    mcp = FastMCP("aggregate_data_mcp")

    @mcp.tool(
        name="extract_metadata",
        annotations={
            "title": "Extract Aggregate Metadata",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def extract_metadata(
        path: str,
        sheet: str | None = None,
        sample_rows: int = 5,
    ) -> dict[str, Any]:
        """Inspect a CSV/XLSX file and return compact aggregation metadata."""
        try:
            return _run_tool(
                lambda: get_service().extract_metadata(
                    path=path,
                    sheet=sheet,
                    sample_rows=sample_rows,
                )
            )
        except Exception as exc:
            LOGGER.exception("extract_metadata failed")
            return _tool_error(exc)

    @mcp.tool(
        name="aggregate_data",
        annotations={
            "title": "Aggregate Data",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def aggregate_data(
        path: str,
        query: str | dict[str, Any] | list[Any],
        sheet: str | None = None,
        table_name: str = "data",
        dataset_id: str | None = None,
        max_rows: int = 1000,
    ) -> dict[str, Any]:
        """Execute read-only SQLite aggregation queries against a CSV/XLSX file."""
        try:
            return _run_tool(
                lambda: get_service().aggregate_data(
                    path=path,
                    query=query,
                    sheet=sheet,
                    table_name=table_name,
                    dataset_id=dataset_id,
                    max_rows=max_rows,
                )
            )
        except Exception as exc:
            LOGGER.exception("aggregate_data failed")
            return _tool_error(exc)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the aggregate_data_mcp server.")
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
