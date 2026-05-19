"""OpenBench skill wrapper for the standalone image-search MCP example."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(_EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_ROOT))

from app.service import get_service  # noqa: E402
from app.tool_schemas import (  # noqa: E402
    INDEX_IMAGES_SCHEMA,
    LIST_INDEX_STATS_SCHEMA,
    REBUILD_INDEX_SCHEMA,
    REMOVE_IMAGE_SCHEMA,
    SEARCH_SIMILAR_IMAGES_SCHEMA,
)


def search_similar_images(
    image_path: str | None = None,
    image_base64: str | None = None,
    image_url: str | None = None,
    cifar10_test_index: int | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Search visually similar CIFAR-10 train images."""
    return get_service().search_similar_images(
        image_path=image_path,
        image_base64=image_base64,
        image_url=image_url,
        cifar10_test_index=cifar10_test_index,
        top_k=top_k,
        threshold=threshold,
    )


def index_images(
    batch_size: int | None = None,
    max_items: int | None = None,
    write_previews: bool = True,
) -> dict[str, Any]:
    """Index missing CIFAR-10 train images."""
    return get_service().index_images(
        batch_size=batch_size,
        max_items=max_items,
        write_previews=write_previews,
    )


def rebuild_index(
    batch_size: int | None = None,
    max_items: int | None = None,
    write_previews: bool = True,
) -> dict[str, Any]:
    """Clear and rebuild the CIFAR-10 train image index."""
    return get_service().rebuild_index(
        batch_size=batch_size,
        max_items=max_items,
        write_previews=write_previews,
    )


def list_index_stats() -> dict[str, Any]:
    """Return image index stats."""
    return get_service().list_index_stats()


def remove_image(image_id: str) -> dict[str, Any]:
    """Remove one indexed image by id."""
    return get_service().remove_image(image_id)
