"""OpenBench skill wrapper for the standalone SAM 3 counting MCP example."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(_EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_ROOT))

from app.service import get_service  # noqa: E402
from app.tool_schemas import COUNT_OBJECTS_WITH_SAM3_SCHEMA, SERVICE_INFO_SCHEMA  # noqa: E402,F401


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
    """Use SAM 3 concept segmentation to count matching object instances."""
    return get_service().count_objects_with_sam3(
        concept=concept,
        image_path=image_path,
        image_base64=image_base64,
        mime_type=mime_type,
        conf=conf,
        min_area_pixels=min_area_pixels,
        return_segments=return_segments,
        return_overlay=return_overlay,
    )


def service_info() -> dict[str, Any]:
    """Return SAM 3 concept counting service metadata."""
    return get_service().service_info()
