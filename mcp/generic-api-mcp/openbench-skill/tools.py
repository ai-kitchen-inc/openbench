"""OpenBench skill wrapper for the standalone generic API MCP example."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(_EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_ROOT))

from app.service import QueryParamValue, get_service  # noqa: E402
from app.tool_schemas import FETCH_GENERIC_API_DATA_SCHEMA  # noqa: E402,F401


def fetch_generic_api_data(
    endpoint_url: str,
    query_params: dict[str, QueryParamValue] | None = None,
) -> dict[str, Any]:
    """Fetch data from the provided API endpoint."""
    return get_service().fetch_generic_api_data(
        endpoint_url=endpoint_url,
        query_params=query_params,
    )
