"""OpenBench skill wrapper for the standalone dashboard-generator MCP server."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_MCP_ROOT = Path(__file__).resolve().parents[1]
if str(_MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_ROOT))

from app.service import bind as _bind_service  # noqa: E402
from app.service import get_service  # noqa: E402
from app.tool_schemas import (  # noqa: E402,F401
    GENERATE_DASHBOARD_SCHEMA,
)


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies."""
    _bind_service(**kwargs)


def generate_dashboard(
    view_model: dict[str, Any],
    filename: str | None = None,
    output_dir: str | None = None,
    template_path: str | None = None,
    template_text: str | None = None,
    template_format: str | None = None,
) -> dict[str, Any]:
    """Create a dashboard artifact from a declarative ViewModel."""
    return get_service().generate_dashboard(
        view_model=view_model,
        filename=filename,
        output_dir=output_dir,
        template_path=template_path,
        template_text=template_text,
        template_format=template_format,
    )
