"""Business logic for the dashboard-generator MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app import dashboard_tools


@dataclass(frozen=True)
class DashboardGeneratorService:
    """Metadata-first dashboard workflow shared by MCP and OpenBench skill tools."""

    def extract_metadata(
        self,
        path: str,
        sheet: str | int | None = None,
        sample_rows: int = 5,
    ) -> dict[str, Any]:
        """Return compact CSV/XLSX metadata for dashboard planning."""
        return dashboard_tools.extract_metadata(
            path=path,
            sheet=sheet,
            sample_rows=sample_rows,
        )

    def aggregate_data(
        self,
        path: str,
        query: str | dict[str, Any] | list[Any],
        sheet: str | int | None = None,
        table_name: str = "data",
        dataset_id: str | None = None,
        max_rows: int = 1000,
    ) -> dict[str, Any]:
        """Run read-only SQLite aggregations over the dashboard source file."""
        return dashboard_tools.aggregate_data(
            path=path,
            query=query,
            sheet=sheet,
            table_name=table_name,
            dataset_id=dataset_id,
            max_rows=max_rows,
        )

    def generate_dashboard(
        self,
        view_model: dict[str, Any],
        filename: str | None = None,
        output_dir: str | None = None,
        template_path: str | None = None,
        template_text: str | None = None,
        template_format: str | None = None,
    ) -> dict[str, Any]:
        """Create a dashboard artifact from a declarative ViewModel."""
        return dashboard_tools.generate_dashboard(
            view_model=view_model,
            filename=filename,
            output_dir=output_dir,
            template_path=template_path,
            template_text=template_text,
            template_format=template_format,
        )


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies for tests or embedded skill use."""
    dashboard_tools.bind(**kwargs)


def get_service() -> DashboardGeneratorService:
    """Build the dashboard service."""
    return DashboardGeneratorService()
