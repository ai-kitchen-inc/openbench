"""LCI Mini — Persona + Skill Layer demo for OpenBench.

A minimal web chat app demonstrating ``openbench.intelligence.Persona``
and ``openbench.intelligence.Skill`` working together:

- **Persona** — agent identity loaded from ``soul/SOUL.md``,
  ``soul/STYLE.md``, and ``soul/AGENTS.md``.
- **Skills** — two project skills loaded from ``skills/``:
  - ``proper-2025/`` — knowledge-only skill with PROPER 2025 context
  - ``unit-converter/`` — tool-bearing skill exposing ``convert_unit``

Unlike the full LCI Ignite X app (which does LDI parsing, Pareto hotspot
analysis, and Excel export), Lici is deliberately small — she answers
LCI/LCA methodology questions, interprets PROPER 2025 requirements, and
can convert common LCA units via the bundled skill tool.

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
