"""FastMCP server entrypoint for local DINOv3 CIFAR-10 image search."""

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
        raise ImportError("Install mcp[cli] to run the image search MCP server") from exc

    mcp = FastMCP("image_search_mcp")

    @mcp.tool(
        name="search_similar_images",
        annotations={
            "title": "Search Similar Images",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def search_similar_images(
        image_path: str | None = None,
        image_base64: str | None = None,
        image_url: str | None = None,
        cifar10_test_index: int | None = None,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Search indexed CIFAR-10 images visually similar to one query image."""
        try:
            return _run_tool(
                lambda: get_service().search_similar_images(
                    image_path=image_path,
                    image_base64=image_base64,
                    image_url=image_url,
                    cifar10_test_index=cifar10_test_index,
                    top_k=top_k,
                    threshold=threshold,
                )
            )
        except Exception as exc:
            return _tool_error(exc)

    @mcp.tool(
        name="index_images",
        annotations={
            "title": "Index CIFAR-10 Images",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def index_images(
        batch_size: int | None = None,
        max_items: int | None = None,
        write_previews: bool = True,
    ) -> dict[str, Any]:
        """Index missing CIFAR-10 images using precomputed embeddings."""
        try:
            return _run_tool(
                lambda: get_service().index_images(
                    batch_size=batch_size,
                    max_items=max_items,
                    write_previews=write_previews,
                )
            )
        except Exception as exc:
            return _tool_error(exc)

    @mcp.tool(
        name="rebuild_index",
        annotations={
            "title": "Rebuild Image Index",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def rebuild_index(
        batch_size: int | None = None,
        max_items: int | None = None,
        write_previews: bool = True,
    ) -> dict[str, Any]:
        """Clear and rebuild the CIFAR-10 vector index."""
        try:
            return _run_tool(
                lambda: get_service().rebuild_index(
                    batch_size=batch_size,
                    max_items=max_items,
                    write_previews=write_previews,
                )
            )
        except Exception as exc:
            return _tool_error(exc)

    @mcp.tool(
        name="list_index_stats",
        annotations={
            "title": "List Image Index Stats",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def list_index_stats() -> dict[str, Any]:
        """Report image search index health, backend, paths, model, and vector counts."""
        try:
            return _run_tool(lambda: get_service().list_index_stats())
        except Exception as exc:
            return _tool_error(exc)

    @mcp.tool(
        name="remove_image",
        annotations={
            "title": "Remove Indexed Image",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def remove_image(image_id: str) -> dict[str, Any]:
        """Remove one indexed image by image_id."""
        try:
            return _run_tool(lambda: get_service().remove_image(image_id))
        except Exception as exc:
            return _tool_error(exc)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the image_search_mcp server.")
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
