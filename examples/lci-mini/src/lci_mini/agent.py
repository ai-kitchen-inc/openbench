"""Lici agent factory — demonstrates OpenBench Persona Layer."""

from __future__ import annotations

import os
from pathlib import Path

from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence import BaseAgent, Persona


def get_persona_dir() -> Path:
    """Return the absolute path to the Lici persona directory.

    The persona lives at ``examples/lci-mini/soul/`` relative to the repo
    root. This helper resolves the path regardless of the current working
    directory so the demo works from anywhere.
    """
    return (Path(__file__).resolve().parents[2] / "soul").resolve()


def create_lici_agent(
    api_key: str | None = None,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.3,
) -> BaseAgent:
    """Create the Lici LCI consultant agent with persona loaded from disk.

    Args:
        api_key: Google Gemini API key. Falls back to ``GOOGLE_API_KEY`` env.
        model: Gemini model id. Must be 2.5+ per project conventions.
        temperature: LLM sampling temperature.

    Returns:
        A :class:`BaseAgent` whose system prompt is composed from
        ``soul/SOUL.md``, ``soul/STYLE.md``, and ``soul/AGENTS.md``.

    Raises:
        RuntimeError: If no Google API key is available.
        FileNotFoundError: If the persona directory is missing.
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
    )
