"""Business logic for the dashboard-generator MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app import dashboard_tools


@dataclass(frozen=True)
class DashboardGeneratorService:
    """Dashboard rendering workflow shared by MCP and OpenBench skill tools."""

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

    def search_dashboards(
        self,
        query: str | None = None,
        source_path: str | None = None,
        template_path: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Search persisted dashboard memory."""
        return dashboard_tools.search_dashboards(
            query=query,
            source_path=source_path,
            template_path=template_path,
            limit=limit,
        )

    def load_dashboard(
        self,
        dashboard_id: str | None = None,
        query: str | None = None,
        latest: bool = False,
    ) -> dict[str, Any]:
        """Load a persisted dashboard artifact."""
        return dashboard_tools.load_dashboard(
            dashboard_id=dashboard_id,
            query=query,
            latest=latest,
        )


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies for tests or embedded skill use."""
    dashboard_tools.bind(**kwargs)


def get_service() -> DashboardGeneratorService:
    """Build the dashboard service."""
    return DashboardGeneratorService()
