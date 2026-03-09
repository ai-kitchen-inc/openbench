"""IO Table Agent for building Input-Output tables from LCI data."""

from __future__ import annotations

from openbench.core.abstractions import DataStore
from openbench.intelligence.base import BaseAgent

from lci_ignite.intelligence.prompts import IO_TABLE_PROMPT
from lci_ignite.intelligence.tools import (
    AGGREGATE_BY_CATEGORY_SCHEMA,
    CREATE_IO_TABLE_CHART_SCHEMA,
    CREATE_IO_TABLE_SCHEMA,
    VALIDATE_UNITS_SCHEMA,
    aggregate_by_category,
    create_io_table,
    create_io_table_chart,
    validate_units,
)


class IOTableAgent(BaseAgent):
    """Agent specialized in building IO tables from LCI data.

    Takes structured LCI data (from EasyLCASource or SimaProCSVSource)
    and creates Input-Output tables with categorized flows.

    Args:
        model: LLM model name. Defaults to "gemini-2.5-flash".
        temperature: Model temperature. Defaults to 0.3 for deterministic output.
        store: Optional DataStore for RAG.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        store: DataStore | None = None,
    ):
        super().__init__(
            goal="Build accurate IO tables from LCI data",
            model=model,
            temperature=temperature,
            max_iterations=5,
            system_prompt=IO_TABLE_PROMPT,
            store=store,
        )

        # Register IO table tools with explicit schemas
        self.tools.register("create_io_table", create_io_table, schema=CREATE_IO_TABLE_SCHEMA)
        self.tools.register(
            "aggregate_by_category", aggregate_by_category, schema=AGGREGATE_BY_CATEGORY_SCHEMA
        )
        self.tools.register("validate_units", validate_units, schema=VALIDATE_UNITS_SCHEMA)
        self.tools.register(
            "create_io_table_chart", create_io_table_chart, schema=CREATE_IO_TABLE_CHART_SCHEMA
        )

    @property
    def agent_type(self) -> str:
        return "io_table"
