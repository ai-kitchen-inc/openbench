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


def bind(**kwargs: Any) -> None:
    """Inject dashboard rendering dependencies for tests or embedded skill use."""
    dashboard_tools.bind(**kwargs)


def get_service() -> DashboardGeneratorService:
    """Build the dashboard service."""
    return DashboardGeneratorService()
