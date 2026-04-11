"""LCI Mini — Persona Layer demo for OpenBench.

A minimal web chat app demonstrating ``openbench.intelligence.Persona``:
agent identity is loaded from ``soul/SOUL.md``, ``soul/STYLE.md``, and
``soul/AGENTS.md`` at startup, with no system prompt hard-coded in Python.

Unlike the full LCI Ignite X app (which does LDI parsing, Pareto hotspot
analysis, and Excel export), Lici is knowledge-only — she answers LCI/LCA
methodology questions and interprets PROPER 2025 requirements.

Entry points:
    server:app           -> FastAPI app for uvicorn
    create_lici_agent    -> BaseAgent factory (used by tests)
"""

from lci_mini.agent import create_lici_agent, get_persona_dir

__all__ = ["create_lici_agent", "get_persona_dir"]
