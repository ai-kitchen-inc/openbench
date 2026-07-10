"""Business logic for the aggregate-data MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app import aggregate_tools


@dataclass(frozen=True)
class AggregateDataService:
    """General-purpose metadata and aggregation workflow."""

    def extract_metadata(
        self,
        path: str,
        sheet: str | int | None = None,
        sample_rows: int = 5,
    ) -> dict[str, Any]:
        """Return compact CSV/XLSX metadata for aggregation planning."""
        return aggregate_tools.extract_metadata(
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
        """Run read-only SQLite aggregations over a tabular file."""
        return aggregate_tools.aggregate_data(
            path=path,
            query=query,
            sheet=sheet,
            table_name=table_name,
            dataset_id=dataset_id,
            max_rows=max_rows,
        )


def get_service() -> AggregateDataService:
    """Build the aggregate service."""
    return AggregateDataService()
