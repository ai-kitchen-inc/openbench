"""Lici agent factory — demonstrates OpenBench Persona + Skill Layers."""

from __future__ import annotations

import os
from pathlib import Path

from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence import BaseAgent, Persona


def _example_root() -> Path:
    """Return examples/lci-mini/ — the example app root directory."""
    return Path(__file__).resolve().parents[2]


def get_persona_dir() -> Path:
    """Return the absolute path to the Lici persona directory.

    The persona lives at ``examples/lci-mini/soul/`` relative to the repo
    root. This helper resolves the path regardless of the current working
    directory so the demo works from anywhere.
    """
    return (_example_root() / "soul").resolve()


def get_skills_dir() -> Path:
    """Return the absolute path to the Lici project skills directory.

    Skills live at ``examples/lci-mini/skills/`` and are loaded as project
    skills (not SDK skills) so they don't pollute the OpenBench SDK.
    """
    return (_example_root() / "skills").resolve()


def get_skill_paths() -> list[str]:
    """Return project skill paths passed to ``BaseAgent(skills=...)``.

    Lici ships with one bundled project skill:

    - ``xql`` — Excel-as-RDBMS skill exposing 14 SQL-like primitives
      (SELECT, WHERE, PROJECT, GROUP BY, JOIN, UNION, PIVOT, PARETO,
      BUILD_IO_TABLE, ...) that treat Excel sheets as relational tables
      with an alias-based schema registry and YAML config for unit
      conversions and LCI grouping rules.
    """
    skills_dir = get_skills_dir()
    return [
        str(skills_dir / "xql"),
    ]


def create_lici_agent(
    api_key: str | None = None,
    model: str = "gemini-3-flash-preview",
    temperature: float = 0.3,
) -> BaseAgent:
    """Create the Lici LCI consultant agent with persona + skills from disk.

    Args:
        api_key: Google Gemini API key. Falls back to ``GOOGLE_API_KEY`` env.
        model: Gemini model id. Must be 2.5+ per project conventions.
        temperature: LLM sampling temperature.

    Returns:
        A :class:`BaseAgent` whose system prompt is composed from
        ``soul/SOUL.md``, ``soul/STYLE.md``, ``soul/AGENTS.md``, plus the
        bundled ``skills/xql`` package (Excel-as-RDBMS). All 14 XQL tools
        — catalog, select, where, project, order, group, distinct,
        pareto, join, union, pivot, build_io_table, list_tables,
        describe_table — are auto-registered on the agent's ToolExecutor
        via the Skill Layer.

    Raises:
        RuntimeError: If no Google API key is available.
        FileNotFoundError: If the persona or skills directories are missing.
    """
    key = api_key or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_API_KEY is required. Set it in the environment or pass api_key=."
        )

    configure_provider(
        name="gemini-lci-mini",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": key},
        settings={"model": model},
        is_default=True,
    )

    persona = Persona.from_dir(get_persona_dir())

    return BaseAgent(
        goal=(
            "Help Indonesian LCA consultants understand LCI methodology, "
            "interpret PROPER 2025 requirements, and reason about environmental "
            "impact data."
        ),
        model=model,
        temperature=temperature,
        persona=persona,
        skills=get_skill_paths(),
    )
