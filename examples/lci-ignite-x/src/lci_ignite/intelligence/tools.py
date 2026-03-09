"""LCA agent tools with ContextVar render-items pattern.

Tools push A2UI visualization data to a ContextVar-backed list.
ChatEngine reads the list after agent execution via render_items_fn.
Same pattern as examples/chat/gemini_agent.py.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Per-request ContextVars ──

_render_items_var: contextvars.ContextVar[list[dict]] = contextvars.ContextVar("lci_render_items")
_current_attachments_var: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "lci_attachments", default=None
)


def _get_render_list() -> list[dict]:
    """Get per-request render items list, creating if needed."""
    try:
        return _render_items_var.get()
    except LookupError:
        items: list[dict] = []
        _render_items_var.set(items)
        return items


def get_render_items() -> list[dict]:
    """Return accumulated render items from tool functions."""
    return list(_get_render_list())


def clear_render_items() -> None:
    """Clear render items queue. Called before each request."""
    _render_items_var.set([])


def set_attachments(attachments: list[dict] | None) -> None:
    """Set file attachments for the current request."""
    _current_attachments_var.set(attachments)


# ── IO Table Tools ──

CREATE_IO_TABLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_io_table",
        "description": (
            "Create an Input-Output table from structured LCI data. "
            "Renders as ObTable in the chat interface."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Table title (e.g., 'IO Table - Cement Production')",
                },
                "process_name": {
                    "type": "string",
                    "description": "Name of the process to build the IO table for",
                },
                "data": {
                    "type": "string",
                    "description": "JSON string of process data with inputs/outputs arrays",
                },
            },
            "required": ["title", "process_name", "data"],
        },
    },
}


def create_io_table(title: str, process_name: str, data: str) -> str:
    """Create an IO table visualization from process data."""
    try:
        process_data = json.loads(data)
    except json.JSONDecodeError:
        return f"Error: Invalid JSON data for process '{process_name}'"

    inputs = process_data.get("inputs", [])
    outputs = process_data.get("outputs", [])

    headers = ["Direction", "Flow", "Category", "Amount", "Unit"]
    rows: list[list[str]] = []

    for flow in inputs:
        rows.append(
            [
                "Input",
                flow.get("flow", ""),
                flow.get("category", flow.get("section", "")),
                str(flow.get("amount", 0)),
                flow.get("unit", ""),
            ]
        )

    for flow in outputs:
        rows.append(
            [
                "Output",
                flow.get("flow", ""),
                flow.get("category", flow.get("section", "")),
                str(flow.get("amount", 0)),
                flow.get("unit", ""),
            ]
        )

    item = {"headers": headers, "rows": rows, "title": title}
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(item)

    return (
        f"IO table created for '{process_name}': "
        f"{len(inputs)} inputs, {len(outputs)} outputs, {len(rows)} total rows."
    )


AGGREGATE_BY_CATEGORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "aggregate_by_category",
        "description": (
            "Aggregate flow amounts by category for a process. "
            "Useful for summarizing inputs/outputs before analysis."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "JSON string of flows array [{flow, category, amount, unit}]",
                },
            },
            "required": ["data"],
        },
    },
}


def aggregate_by_category(data: str) -> str:
    """Aggregate flow amounts by category."""
    try:
        flows = json.loads(data)
    except json.JSONDecodeError:
        return "Error: Invalid JSON data"

    aggregated: dict[str, dict[str, float | str]] = {}
    for flow in flows:
        cat = flow.get("category", flow.get("section", "Unknown"))
        amount = float(flow.get("amount", 0))
        unit = flow.get("unit", "")

        if cat not in aggregated:
            aggregated[cat] = {"total": 0.0, "unit": unit, "count": 0}
        aggregated[cat]["total"] += amount
        aggregated[cat]["count"] = int(aggregated[cat]["count"]) + 1

    result = {
        cat: {"total": round(info["total"], 4), "unit": info["unit"], "count": info["count"]}
        for cat, info in aggregated.items()
    }
    return json.dumps(result, indent=2)


VALIDATE_UNITS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_units",
        "description": (
            "Validate unit consistency within a category. Reports any category with mixed units."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "JSON string of flows array [{flow, category, amount, unit}]",
                },
            },
            "required": ["data"],
        },
    },
}


def validate_units(data: str) -> str:
    """Validate that flows in the same category use consistent units."""
    try:
        flows = json.loads(data)
    except json.JSONDecodeError:
        return "Error: Invalid JSON data"

    category_units: dict[str, set[str]] = {}
    for flow in flows:
        cat = flow.get("category", flow.get("section", "Unknown"))
        unit = flow.get("unit", "")
        if cat not in category_units:
            category_units[cat] = set()
        category_units[cat].add(unit)

    issues = []
    for cat, units in category_units.items():
        if len(units) > 1:
            issues.append(f"Category '{cat}' has mixed units: {sorted(units)}")

    if issues:
        return "Unit validation issues found:\n" + "\n".join(issues)
    return "All categories have consistent units."


CREATE_IO_TABLE_CHART_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_io_table_chart",
        "description": (
            "Create a bar chart visualization of IO table data, "
            "showing flow amounts grouped by category."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Chart title"},
                "data": {
                    "type": "string",
                    "description": (
                        "JSON string of chart data array [{category, amount, direction}]"
                    ),
                },
            },
            "required": ["title", "data"],
        },
    },
}


def create_io_table_chart(title: str, data: str) -> str:
    """Create a bar chart for IO table data."""
    try:
        chart_data = json.loads(data)
    except json.JSONDecodeError:
        return "Error: Invalid JSON data for chart"

    item: dict[str, Any] = {
        "type": "bar",
        "title": title,
        "data": chart_data,
    }

    items = _get_render_list()
    items[:] = [i for i in items if not (i.get("title") == title and "data" in i)]
    items.append(item)

    return f"IO chart created: '{title}' with {len(chart_data)} data points."


# ── Hotspot Analysis Tools ──

CALCULATE_PARETO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculate_pareto",
        "description": (
            "Perform Pareto analysis on environmental impact data. "
            "Identifies the top contributors that account for the given "
            "threshold percentage (default 80%) of total impact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "impacts": {
                    "type": "string",
                    "description": (
                        "JSON string of impact data array [{name, amount, unit, category}]"
                    ),
                },
                "threshold": {
                    "type": "number",
                    "description": "Cumulative percentage threshold (default 80.0)",
                },
            },
            "required": ["impacts"],
        },
    },
}


def calculate_pareto(impacts: str, threshold: float = 80.0) -> str:
    """Perform Pareto analysis on environmental impact data.

    Sorts impacts by amount descending, calculates cumulative percentage,
    and identifies items contributing to the threshold percentage.
    """
    try:
        impact_list = json.loads(impacts)
    except json.JSONDecodeError:
        return "Error: Invalid JSON data for Pareto analysis"

    if not impact_list:
        return "Error: Empty impact data"

    # Sort by absolute amount descending
    sorted_impacts = sorted(impact_list, key=lambda x: abs(float(x.get("amount", 0))), reverse=True)

    total = sum(abs(float(item.get("amount", 0))) for item in sorted_impacts)
    if total == 0:
        return "Error: Total impact is zero"

    cumulative = 0.0
    hotspots = []
    non_hotspots = []

    for item in sorted_impacts:
        amount = abs(float(item.get("amount", 0)))
        pct = (amount / total) * 100
        cumulative += pct

        entry = {
            "name": item.get("name", item.get("flow", "")),
            "amount": float(item.get("amount", 0)),
            "unit": item.get("unit", ""),
            "category": item.get("category", ""),
            "percentage": round(pct, 2),
            "cumulative_percentage": round(cumulative, 2),
            "is_hotspot": cumulative <= threshold or len(hotspots) == 0,
        }

        if entry["is_hotspot"]:
            hotspots.append(entry)
        else:
            non_hotspots.append(entry)

    result = {
        "hotspots": hotspots,
        "non_hotspots": non_hotspots,
        "total": round(total, 4),
        "threshold": threshold,
        "hotspot_count": len(hotspots),
        "hotspot_percentage": round(sum(h["percentage"] for h in hotspots), 2),
    }

    return json.dumps(result, indent=2)


CREATE_PARETO_CHART_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_pareto_chart",
        "description": (
            "Create a Pareto chart showing environmental impact distribution. "
            "Bar chart with cumulative percentage line."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Chart title"},
                "data": {
                    "type": "string",
                    "description": (
                        "JSON string of Pareto data array "
                        "[{name, percentage, cumulative_percentage}]"
                    ),
                },
            },
            "required": ["title", "data"],
        },
    },
}


def create_pareto_chart(title: str, data: str) -> str:
    """Create a Pareto chart visualization."""
    try:
        chart_data = json.loads(data)
    except json.JSONDecodeError:
        return "Error: Invalid JSON data for Pareto chart"

    item: dict[str, Any] = {
        "type": "bar",
        "title": title,
        "data": chart_data,
        "options": {
            "xKey": "name",
            "series": [
                {"dataKey": "percentage", "name": "Impact %"},
            ],
        },
    }

    items = _get_render_list()
    items[:] = [i for i in items if not (i.get("title") == title and "data" in i)]
    items.append(item)

    return f"Pareto chart created: '{title}' with {len(chart_data)} items."


CREATE_HOTSPOT_TABLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_hotspot_table",
        "description": (
            "Create a table summarizing environmental hotspots. "
            "Renders as ObTable in the chat interface."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Table title"},
                "headers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column headers",
                },
                "rows": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                    "description": "Table rows (2D array of strings)",
                },
            },
            "required": ["title", "headers", "rows"],
        },
    },
}


def create_hotspot_table(title: str, headers: list[str], rows: list[list[str]]) -> str:
    """Create a hotspot summary table."""
    item = {"headers": headers, "rows": rows, "title": title}
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(item)

    return f"Hotspot table created: '{title}' with {len(headers)} columns and {len(rows)} rows."


CREATE_HOTSPOT_CALLOUT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_hotspot_callout",
        "description": (
            "Display a callout box highlighting key findings from hotspot analysis. "
            "Renders as ObCallout in the chat interface."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Callout content (markdown supported)",
                },
                "variant": {
                    "type": "string",
                    "enum": ["default", "info", "warning", "error", "success"],
                    "description": "Callout style variant (default: 'warning')",
                },
                "title": {
                    "type": "string",
                    "description": "Optional callout title",
                },
            },
            "required": ["content"],
        },
    },
}


def create_hotspot_callout(content: str, variant: str = "warning", title: str = "") -> str:
    """Display a callout highlighting hotspot findings."""
    item: dict[str, Any] = {"calloutContent": content, "variant": variant}
    if title:
        item["title"] = title
    items = _get_render_list()
    items[:] = [i for i in items if "calloutContent" not in i]
    items.append(item)

    return f"Hotspot callout displayed: '{title or variant}' variant."


# ── Narrative Tools ──

CREATE_NARRATIVE_MARKDOWN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_narrative_markdown",
        "description": (
            "Render a narrative explanation section as rich markdown. "
            "Used for hotspot explanations and PROPER 2025 recommendations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Section title"},
                "content": {
                    "type": "string",
                    "description": "Markdown content for the narrative section",
                },
            },
            "required": ["title", "content"],
        },
    },
}


def create_narrative_markdown(title: str, content: str) -> str:
    """Render a narrative markdown section. No A2UI push — text goes through streaming."""
    return f"## {title}\n\n{content}"


CREATE_NARRATIVE_CALLOUT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_narrative_callout",
        "description": (
            "Display a callout for key narrative insights or PROPER 2025 recommendations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Callout content"},
                "variant": {
                    "type": "string",
                    "enum": ["default", "info", "warning", "success"],
                    "description": "Callout style (default: 'info')",
                },
                "title": {"type": "string", "description": "Optional title"},
            },
            "required": ["content"],
        },
    },
}


def create_narrative_callout(content: str, variant: str = "info", title: str = "") -> str:
    """Display a callout for narrative insights."""
    item: dict[str, Any] = {"calloutContent": content, "variant": variant}
    if title:
        item["title"] = title
    items = _get_render_list()
    # Allow multiple callouts in narrative (unlike hotspot which replaces)
    items.append(item)

    return f"Narrative callout displayed: '{title or variant}'."


# ── Export Tool ──

EXPORT_TO_DOCX_SCHEMA = {
    "type": "function",
    "function": {
        "name": "export_to_docx",
        "description": (
            "Export the LCA analysis results to a .docx report file. "
            "Triggers DocxReportGenerator and shows a file download card."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title"},
                "content": {
                    "type": "string",
                    "description": "JSON string of report content sections",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (default: lca_report.docx)",
                },
            },
            "required": ["title", "content"],
        },
    },
}


def export_to_docx(title: str, content: str, filename: str = "lca_report.docx") -> str:
    """Export LCA report to .docx format.

    This is a placeholder — actual generation happens via DocxReportGenerator
    in Sprint 4. For now, pushes a file card with pending status.
    """
    item: dict[str, Any] = {
        "name": filename,
        "url": f"/uploads/{filename}",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 0,
    }
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("name") == filename and "url" in i and "mimeType" in i)
    ]
    items.append(item)

    return f"Report export initiated: '{title}' → {filename}"
