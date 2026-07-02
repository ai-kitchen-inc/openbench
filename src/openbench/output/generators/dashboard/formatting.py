"""HTML-escaping and value-formatting helpers for dashboard rendering."""

from __future__ import annotations

import html
import json
import math
import re
from typing import Any


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:48] or "dashboard"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        if abs(value) >= 1000:
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}" if abs(value) >= 1000 else str(value)
    if isinstance(value, list):
        return ", ".join(filter(None, (_format_value(item) for item in value)))
    if isinstance(value, dict):
        for key in ("value", "label", "name", "title"):
            if key in value:
                return _format_value(value.get(key))
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)
