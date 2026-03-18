"""IO Table Agent for building Input-Output tables from LCI data."""

from __future__ import annotations

from openbench.core.abstractions import DataStore
from openbench.intelligence.base import BaseAgent

from lci_ignite.intelligence.prompts import IO_TABLE_PROMPT
from lci_ignite.intelligence.tools import (
    # Existing IO table tools
    AGGREGATE_BY_CATEGORY_SCHEMA,
    # New data processing tools (Phase 3)
    ANALYZE_EXCEL_STRUCTURE_SCHEMA,
    APPLY_UNIT_CONVERSIONS_SCHEMA,
    BUILD_PROPER_IO_TABLE_SCHEMA,
    CALCULATE_FUNCTIONAL_UNIT_SCHEMA,
    CREATE_IO_TABLE_CHART_SCHEMA,
    CREATE_IO_TABLE_SCHEMA,
    PARSE_LDI_SHEET_SCHEMA,
    SELECT_PARETO_ITEMS_SCHEMA,
    VALIDATE_DATA_QUALITY_SCHEMA,
    VALIDATE_UNITS_SCHEMA,
    aggregate_by_category,
    analyze_excel_structure,
    apply_unit_conversions,
    build_proper_io_table,
    calculate_functional_unit,
    create_io_table,
    create_io_table_chart,
    parse_ldi_sheet,
    select_pareto_items,
    validate_data_quality,
    validate_units,
)


class IOTableAgent(BaseAgent):
    """Agent specialized in building IO tables from LCI data.

    Handles both CSV (easyLCA/SimaPro) and Excel LDI formats.
    For Excel: uses the full data processing pipeline (analyze -> parse ->
    convert -> Pareto -> FU -> build PROPER IO Table).
    For CSV: uses the simpler create_io_table flow.

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
            max_iterations=8,
            system_prompt=IO_TABLE_PROMPT,
            store=store,
        )

        # Data processing tools (Excel LDI pipeline)
        self.tools.register(
            "analyze_excel_structure",
            analyze_excel_structure,
            schema=ANALYZE_EXCEL_STRUCTURE_SCHEMA,
        )
        self.tools.register("parse_ldi_sheet", parse_ldi_sheet, schema=PARSE_LDI_SHEET_SCHEMA)
        self.tools.register(
            "apply_unit_conversions",
            apply_unit_conversions,
            schema=APPLY_UNIT_CONVERSIONS_SCHEMA,
        )
        self.tools.register(
            "calculate_functional_unit",
            calculate_functional_unit,
            schema=CALCULATE_FUNCTIONAL_UNIT_SCHEMA,
        )
        self.tools.register(
            "select_pareto_items", select_pareto_items, schema=SELECT_PARETO_ITEMS_SCHEMA
        )
        self.tools.register(
            "validate_data_quality", validate_data_quality, schema=VALIDATE_DATA_QUALITY_SCHEMA
        )
        self.tools.register(
            "build_proper_io_table", build_proper_io_table, schema=BUILD_PROPER_IO_TABLE_SCHEMA
        )

        # IO table tools (CSV flow + visualization)
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
