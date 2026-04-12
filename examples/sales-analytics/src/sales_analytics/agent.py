"""Agent factory for the Sales Analytics demo.

Creates a BaseAgent with:
- Persona from soul/ (sales analyst identity)
- SDK skills ONLY (no project skills)
- Gemini as LLM provider

This proves that OpenBench SDK skills are sufficient for a complete
analytics workflow without any domain-specific tooling.
"""

from __future__ import annotations

import os
from pathlib import Path

from openbench.intelligence.base import BaseAgent


def get_persona_dir() -> Path:
    """Return the soul/ directory for the sales analyst persona."""
    return Path(__file__).resolve().parents[2] / "soul"


def create_analyst_agent(
    api_key: str | None = None,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.3,
) -> BaseAgent:
    """Create the sales analyst agent with persona + SDK skills only.

    No project skills, no aliases.yaml, no domain config. Everything
    the agent needs comes from:
    - soul/ persona files (identity + rules)
    - SDK skills auto-discovered by SkillRegistry (7 tools from
      data-context-extractor, 5 from query-explorer, 5 from
      data-visualization, 2 from export-excel, 2 from web-search)
    """
    if api_key:
        os.environ["GOOGLE_API_KEY"] = api_key

    return BaseAgent(
        goal="Analyze sales data, identify trends, and help the user make data-driven decisions",
        persona=str(get_persona_dir()),
        # SDK skills only — pass by name so SkillRegistry creates + loads.
        # No project skill paths needed.
        skills=[
            "data-context-extractor",
            "query-explorer",
            "data-visualization",
            "export-excel",
            "web-search",
        ],
        model=model,
        temperature=temperature,
        max_iterations=15,
    )
