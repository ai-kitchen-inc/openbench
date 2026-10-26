"""LCI Mini — Persona + Skill Layer demo for OpenBench.

A minimal web chat app demonstrating ``openbench.intelligence.Persona``
and ``openbench.intelligence.Skill`` working together:

- **Persona** — agent identity loaded from ``soul/SOUL.md``,
  ``soul/STYLE.md``, and ``soul/AGENTS.md``.
- **Skills** — one project skill loaded from ``skills/``:
  - ``xql/`` — Excel Query Language (SQL-like primitives over .xlsx
    workbooks: SELECT, WHERE, GROUP, PARETO, JOIN, PIVOT, etc.)

  Plus any SDK skills (data-context-extractor, data-visualization,
  export-excel, query-explorer) auto-discovered from the OpenBench
  package.

Lici answers LCI/LCA methodology questions, interprets PROPER 2025
requirements, and uses xql tools to analyze uploaded Excel workbooks.

Entry points:
    server:app           -> FastAPI app for uvicorn
    create_lici_agent    -> BaseAgent factory (used by tests)
"""

from lci_mini.agent import (
    create_lici_agent,
    get_persona_dir,
    get_skill_paths,
    get_skills_dir,
)

__all__ = [
    "create_lici_agent",
    "get_persona_dir",
    "get_skills_dir",
    "get_skill_paths",
]
