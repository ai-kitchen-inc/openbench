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
    AGGREGATE_DATA_SCHEMA,
    EXTRACT_METADATA_SCHEMA,
    GENERATE_DASHBOARD_SCHEMA,
)


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies."""
    _bind_service(**kwargs)


def extract_metadata(
    path: str,
    sheet: str | int | None = None,
    sample_rows: int = 5,
) -> dict[str, Any]:
    """Return compact metadata for a CSV/XLSX dashboard source."""
    return get_service().extract_metadata(path=path, sheet=sheet, sample_rows=sample_rows)


def aggregate_data(
    path: str,
    query: str | dict[str, Any] | list[Any],
    sheet: str | int | None = None,
    table_name: str = "data",
    dataset_id: str | None = None,
    max_rows: int = 1000,
) -> dict[str, Any]:
    """Execute read-only SQL aggregation queries against a CSV/XLSX file."""
    return get_service().aggregate_data(
        path=path,
        query=query,
        sheet=sheet,
        table_name=table_name,
        dataset_id=dataset_id,
        max_rows=max_rows,
    )


def generate_dashboard(
    view_model: dict[str, Any],
    filename: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Create a dashboard artifact from a declarative ViewModel."""
    return get_service().generate_dashboard(
        view_model=view_model,
        filename=filename,
        output_dir=output_dir,
    )
