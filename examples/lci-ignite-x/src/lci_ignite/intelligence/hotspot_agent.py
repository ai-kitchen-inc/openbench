"""Hotspot Analysis Agent for environmental impact assessment."""

from __future__ import annotations

from openbench.core.abstractions import DataStore
from openbench.intelligence.base import BaseAgent

from lci_ignite.intelligence.prompts import HOTSPOT_PROMPT
from lci_ignite.intelligence.tools import (
    CALCULATE_PARETO_SCHEMA,
    CREATE_HOTSPOT_CALLOUT_SCHEMA,
    CREATE_HOTSPOT_TABLE_SCHEMA,
    CREATE_PARETO_CHART_SCHEMA,
    calculate_pareto,
    create_hotspot_callout,
    create_hotspot_table,
    create_pareto_chart,
)


class HotspotAnalysisAgent(BaseAgent):
    """Agent specialized in environmental hotspot analysis using Pareto.

    Identifies the top environmental impact contributors (80/20 rule)
    and cross-references with PROPER 2025 criteria via RAG.

    Args:
        model: LLM model name. Defaults to "gemini-2.5-flash".
        temperature: Model temperature. Defaults to 0.3.
        store: Optional DataStore for PROPER 2025 RAG.
        retrieval_top_k: Number of RAG results. Defaults to 5.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        store: DataStore | None = None,
        retrieval_top_k: int = 5,
    ):
        super().__init__(
            goal="Identify environmental hotspots using Pareto analysis",
            model=model,
            temperature=temperature,
            max_iterations=8,
            system_prompt=HOTSPOT_PROMPT,
            store=store,
            retrieval_top_k=retrieval_top_k,
            multi_hop_rag=True,  # Auto-registers retrieve_knowledge tool
        )

        # Register hotspot analysis tools
        self.tools.register("calculate_pareto", calculate_pareto, schema=CALCULATE_PARETO_SCHEMA)
        self.tools.register(
            "create_pareto_chart", create_pareto_chart, schema=CREATE_PARETO_CHART_SCHEMA
        )
        self.tools.register(
            "create_hotspot_table", create_hotspot_table, schema=CREATE_HOTSPOT_TABLE_SCHEMA
        )
        self.tools.register(
            "create_hotspot_callout", create_hotspot_callout, schema=CREATE_HOTSPOT_CALLOUT_SCHEMA
        )

    @property
    def agent_type(self) -> str:
        return "hotspot_analysis"
