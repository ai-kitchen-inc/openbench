"""Narrative Hotspot Agent for generating contextual LCA explanations."""

from __future__ import annotations

from typing import Any

from openbench.core.abstractions import DataStore
from openbench.intelligence.base import BaseAgent

from lci_ignite.intelligence.prompts import NARRATIVE_PROMPT
from lci_ignite.intelligence.tools import (
    CREATE_NARRATIVE_CALLOUT_SCHEMA,
    CREATE_NARRATIVE_MARKDOWN_SCHEMA,
    EXPORT_TO_DOCX_SCHEMA,
    create_narrative_callout,
    create_narrative_markdown,
    export_to_docx,
)


class NarrativeHotspotAgent(BaseAgent):
    """Agent specialized in generating narrative explanations for LCA hotspots.

    Creates contextual, professional narratives with PROPER 2025 references,
    suitable for regulatory submission documents.

    Args:
        model: LLM model name. Defaults to "gemini-2.5-flash".
        temperature: Higher temperature for more creative writing. Defaults to 0.7.
        store: Optional DataStore for PROPER 2025 RAG.
        retrieval_top_k: Number of RAG results. Defaults to 8.
        memory_store: Optional MemoryStore for persistent memory.
        session_id: Session ID for persistent memory.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        store: DataStore | None = None,
        retrieval_top_k: int = 8,
        memory_store: Any = None,
        session_id: str | None = None,
    ):
        super().__init__(
            goal="Generate contextual narrative explanations for LCA hotspots",
            model=model,
            temperature=temperature,
            max_iterations=6,
            system_prompt=NARRATIVE_PROMPT,
            store=store,
            retrieval_top_k=retrieval_top_k,
            multi_hop_rag=True,
            memory_store=memory_store,
            session_id=session_id,
        )

        # Register narrative tools
        self.tools.register(
            "create_narrative_markdown",
            create_narrative_markdown,
            schema=CREATE_NARRATIVE_MARKDOWN_SCHEMA,
        )
        self.tools.register(
            "create_narrative_callout",
            create_narrative_callout,
            schema=CREATE_NARRATIVE_CALLOUT_SCHEMA,
        )
        self.tools.register("export_to_docx", export_to_docx, schema=EXPORT_TO_DOCX_SCHEMA)

    @property
    def agent_type(self) -> str:
        return "narrative_hotspot"
