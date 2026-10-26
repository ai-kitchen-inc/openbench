"""Tools for the data-visualization SDK skill.

Every tool returns a plain dict in the shape consumed by
``openbench.chat.renderers.chart.ChartRenderer``::

    {"type": "bar"|"line"|"pie"|"scatter"|"area",
     "title": str | None,
     "data": list[dict],
     "options": dict}

These dicts are meant to be collected via ``ChatEngine(render_items_fn=...)``
and rendered as ObChart components in the assistant's next turn. The tools
do not touch matplotlib, recharts, or any rendering library themselves —
they only shape the data.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = [
    "create_bar_chart",
    "create_line_chart",
    "create_pie_chart",
    "create_scatter_chart",
    "create_area_chart",
    "CREATE_BAR_CHART_SCHEMA",
    "CREATE_LINE_CHART_SCHEMA",
    "CREATE_PIE_CHART_SCHEMA",
    "CREATE_SCATTER_CHART_SCHEMA",
    "CREATE_AREA_CHART_SCHEMA",
]

logger = logging.getLogger(__name__)


_MAX_PIE_SLICES = 8


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _normalize_records(
    data: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> list[dict[str, Any]] | dict[str, Any]:
    """Validate records contain the required keys.

    Returns the same list on success, or an error dict on failure.
    """
    if not isinstance(data, list) or not data:
        return _error("`data` must be a non-empty list of records")
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            return _error(f"data[{i}] is not a dict")
        for key in keys:
            if key not in row:
                return _error(f"data[{i}] is missing required key {key!r}")
    return data


def _push_to_render_queue(item: dict[str, Any]) -> None:
    """Push chart item onto the shared render queue if available.

    Lazily imports so the skill loads without the chat extras.
    Silently no-ops on any failure — the tool still returns the dict
    to the LLM as tool-result context.
    """
    try:
        from openbench.chat.render_queue import push as _push
    except Exception as e:
        logger.debug("chart-push: render queue unavailable: %s", e)
        return
    try:
        _push(item)
        from openbench.chat.render_queue import get_items

        logger.debug("chart-push: queued item, %d in queue", len(get_items()))
    except Exception as e:
        logger.warning("chart-push: failed to push item: %s", e)


def _chart_dict(
    chart_type: str,
    title: str | None,
    data: list[dict[str, Any]],
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"type": chart_type, "data": data}
    if title:
        out["title"] = title
    if options:
        out["options"] = options
    return out


# ---------------------------------------------------------------------------
# create_bar_chart
# ---------------------------------------------------------------------------


def create_bar_chart(
    title: str,
    data: list[dict[str, Any]],
    x_key: str = "name",
    y_key: str = "value",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bar chart render item.

    Args:
        title: Chart title — should name both the measure and the scope.
        data: Records with at least ``x_key`` and ``y_key`` fields.
        x_key: Name of the categorical field (default ``"name"``).
        y_key: Name of the numeric field (default ``"value"``).
        options: Optional extra chart config (e.g. color, orientation).
    """
    validated = _normalize_records(data, (x_key, y_key))
    if isinstance(validated, dict):
        return validated
    merged_options = {"xKey": x_key, "yKey": y_key}
    if options:
        merged_options.update(options)
    item = _chart_dict("bar", title, validated, merged_options)
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# create_line_chart
# ---------------------------------------------------------------------------


def create_line_chart(
    title: str,
    data: list[dict[str, Any]],
    x_key: str = "x",
    y_key: str = "y",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a line chart render item (time series / continuous trend)."""
    validated = _normalize_records(data, (x_key, y_key))
    if isinstance(validated, dict):
        return validated
    merged_options = {"xKey": x_key, "yKey": y_key}
    if options:
        merged_options.update(options)
    item = _chart_dict("line", title, validated, merged_options)
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# create_pie_chart
# ---------------------------------------------------------------------------


def create_pie_chart(
    title: str,
    data: list[dict[str, Any]],
    name_key: str = "name",
    value_key: str = "value",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a pie chart render item.

    Warns (via an ``options.warning`` field) when more than 8 slices are
    passed — the chart is still returned, but the agent should consider
    a bar chart instead.
    """
    validated = _normalize_records(data, (name_key, value_key))
    if isinstance(validated, dict):
        return validated
    merged_options: dict[str, Any] = {"nameKey": name_key, "valueKey": value_key}
    if len(validated) > _MAX_PIE_SLICES:
        merged_options["warning"] = (
            f"Pie chart has {len(validated)} slices; "
            f"consider a bar chart for readability (>={_MAX_PIE_SLICES + 1})."
        )
    if options:
        merged_options.update(options)
    item = _chart_dict("pie", title, validated, merged_options)
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# create_scatter_chart
# ---------------------------------------------------------------------------


def create_scatter_chart(
    title: str,
    data: list[dict[str, Any]],
    x_key: str = "x",
    y_key: str = "y",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a scatter chart render item."""
    validated = _normalize_records(data, (x_key, y_key))
    if isinstance(validated, dict):
        return validated
    merged_options = {"xKey": x_key, "yKey": y_key}
    if options:
        merged_options.update(options)
    item = _chart_dict("scatter", title, validated, merged_options)
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# create_area_chart
# ---------------------------------------------------------------------------


def create_area_chart(
    title: str,
    data: list[dict[str, Any]],
    x_key: str = "x",
    y_key: str = "y",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an area chart render item (cumulative/stacked trend)."""
    validated = _normalize_records(data, (x_key, y_key))
    if isinstance(validated, dict):
        return validated
    merged_options = {"xKey": x_key, "yKey": y_key}
    if options:
        merged_options.update(options)
    item = _chart_dict("area", title, validated, merged_options)
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_COMMON_DATA_PROP = {
    "type": "array",
    "description": "List of records — each record is an object with at least the x/y (or name/value) keys.",
    "items": {"type": "object"},
}


CREATE_BAR_CHART_SCHEMA = _schema(
    "create_bar_chart",
    "Build a bar chart render item for categorical comparison or top-N ranking.",
    {
        "title": {"type": "string"},
        "data": _COMMON_DATA_PROP,
        "x_key": {"type": "string", "description": "Categorical field name (default 'name')"},
        "y_key": {"type": "string", "description": "Numeric field name (default 'value')"},
    },
    ["title", "data"],
)

CREATE_LINE_CHART_SCHEMA = _schema(
    "create_line_chart",
    "Build a line chart render item for a time series or continuous-axis trend.",
    {
        "title": {"type": "string"},
        "data": _COMMON_DATA_PROP,
        "x_key": {"type": "string", "description": "X-axis field name (default 'x')"},
        "y_key": {"type": "string", "description": "Y-axis field name (default 'y')"},
    },
    ["title", "data"],
)

CREATE_PIE_CHART_SCHEMA = _schema(
    "create_pie_chart",
    "Build a pie chart render item for a share-of-total breakdown. Prefer "
    "a bar chart when there are more than ~8 slices.",
    {
        "title": {"type": "string"},
        "data": _COMMON_DATA_PROP,
        "name_key": {"type": "string", "description": "Slice label field (default 'name')"},
        "value_key": {"type": "string", "description": "Slice numeric field (default 'value')"},
    },
    ["title", "data"],
)

CREATE_SCATTER_CHART_SCHEMA = _schema(
    "create_scatter_chart",
    "Build a scatter chart render item showing the correlation between two numeric fields.",
    {
        "title": {"type": "string"},
        "data": _COMMON_DATA_PROP,
        "x_key": {"type": "string"},
        "y_key": {"type": "string"},
    },
    ["title", "data"],
)

CREATE_AREA_CHART_SCHEMA = _schema(
    "create_area_chart",
    "Build an area chart render item for cumulative or stacked trends over a continuous axis.",
    {
        "title": {"type": "string"},
        "data": _COMMON_DATA_PROP,
        "x_key": {"type": "string"},
        "y_key": {"type": "string"},
    },
    ["title", "data"],
)
