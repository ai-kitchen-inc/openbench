"""Reusable MCP prompts for OpenBench benchmark workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPPrompt:
    """A reusable prompt template."""

    name: str
    description: str
    arguments: list[dict[str, Any]] = field(default_factory=list)
    template: str = ""

    def to_mcp_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }

    def render(self, **kwargs: Any) -> str:
        return self.template.format(**{k: v or "" for k, v in kwargs.items()})


DEFAULT_PROMPTS: dict[str, MCPPrompt] = {
    "analyze_uploaded_data": MCPPrompt(
        name="analyze_uploaded_data",
        description="Analyze an uploaded CSV, Excel, or JSON file using OpenBench data tools.",
        arguments=[
            {"name": "path", "description": "Path to the uploaded file", "required": True},
            {"name": "question", "description": "User analysis question", "required": False},
        ],
        template=(
            "Inspect the uploaded file at {path}. First call extract_file_context, "
            "then use query and visualization tools as needed to answer: {question}"
        ),
    ),
    "summarize_pdf": MCPPrompt(
        name="summarize_pdf",
        description="Summarize or inspect a PDF with page-aware reading tools.",
        arguments=[
            {"name": "path", "description": "Path to the PDF", "required": True},
            {"name": "focus", "description": "Summary focus", "required": False},
        ],
        template=(
            "Use pdf_metadata on {path}, then read relevant pages and summarize "
            "the document. Focus: {focus}"
        ),
    ),
    "build_chart_from_records": MCPPrompt(
        name="build_chart_from_records",
        description="Create a chart from records returned by OpenBench data tools.",
        arguments=[
            {"name": "chart_type", "description": "bar, line, pie, scatter, or area"},
            {"name": "goal", "description": "What the chart should show"},
        ],
        template=(
            "Create a {chart_type} chart that clearly shows: {goal}. Use the "
            "OpenBench chart tool whose output best matches the chart type."
        ),
    ),
    "export_report": MCPPrompt(
        name="export_report",
        description="Export analysis results to a durable artifact.",
        arguments=[
            {"name": "format", "description": "excel or pdf", "required": True},
            {"name": "title", "description": "Report title", "required": False},
        ],
        template=(
            "Prepare a {format} artifact for this analysis. Use a concise title: {title}. "
            "Return the generated file card or resource link."
        ),
    ),
}
