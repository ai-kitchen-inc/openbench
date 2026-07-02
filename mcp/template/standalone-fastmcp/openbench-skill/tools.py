"""OpenBench skill wrapper for the example MCP template."""

from __future__ import annotations

import sys
from pathlib import Path

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(_EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_ROOT))

from app.service import get_service  # noqa: E402
from app.tool_schemas import EXAMPLE_ECHO_SCHEMA  # noqa: E402,F401


def example_echo(text: str, uppercase: bool = False) -> dict[str, str | int | bool]:
    """Echo text with optional uppercase formatting."""
    return get_service().echo(text=text, uppercase=uppercase)
