"""FastMCP entrypoint for local SAM 3 concept counting."""

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
        raise ImportError("Install mcp[cli] to run the SAM 3 counting MCP server") from exc

    mcp = FastMCP("sam_segmentation_mcp")

    @mcp.tool(
        name="count_objects_with_sam3",
        annotations={
            "title": "Count Objects With SAM 3",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def count_objects_with_sam3(
        concept: str,
        image_path: str | None = None,
        image_base64: str | None = None,
        mime_type: str | None = None,
        conf: float | None = None,
        min_area_pixels: int | None = None,
        return_segments: bool = True,
        return_overlay: bool | None = None,
    ) -> dict[str, Any]:
        """Use SAM 3 concept segmentation to count all instances of a text concept.

        Provide a short noun phrase such as "dog", "person", "red apple",
        "yellow school bus", or "person wearing a hat". This server is SAM 3
        only and does not support model selection.
        """
        try:
            return _run_tool(
                lambda: get_service().count_objects_with_sam3(
                    concept=concept,
                    image_path=image_path,
                    image_base64=image_base64,
                    mime_type=mime_type,
                    conf=conf,
                    min_area_pixels=min_area_pixels,
                    return_segments=return_segments,
                    return_overlay=return_overlay,
                )
            )
        except Exception as exc:
            LOGGER.exception("count_objects_with_sam3 failed")
            return _tool_error(exc)

    @mcp.tool(
        name="service_info",
        annotations={
            "title": "SAM 3 Counting Service Info",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def service_info() -> dict[str, Any]:
        """Report SAM 3 service configuration and model weight status."""
        try:
            return _run_tool(lambda: get_service().service_info())
        except Exception as exc:
            LOGGER.exception("service_info failed")
            return _tool_error(exc)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sam_segmentation_mcp server.")
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
