"""General Chat agent factory."""

from __future__ import annotations

import os
from pathlib import Path

from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence import BaseAgent, Persona


def _example_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_persona_dir() -> Path:
    return (_example_root() / "soul").resolve()


def create_agent(
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
) -> BaseAgent:
    """Create the general-purpose chat agent.

    Loads persona from ``soul/`` and wires SDK skills for spreadsheet/data
    operations. No project-specific skills — works with any uploaded document.
    """
    key = api_key or os.getenv("GOOGLE_API_KEY")
    resolved_model = model or os.getenv("GENERAL_CHAT_MODEL", "gemini-3-flash-preview")
    if not key:
        raise RuntimeError(
            "GOOGLE_API_KEY is required. Set it in .env or the environment."
        )

    configure_provider(
        name="gemini-general-chat",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": key},
        settings={"model": resolved_model},
        is_default=True,
    )

    persona_dir = get_persona_dir()
    persona = Persona.from_dir(persona_dir) if persona_dir.is_dir() else None

    return BaseAgent(
        goal=(
            "Help users by answering questions, analysing uploaded documents "
            "(PDF, Word, PowerPoint), and reasoning over data."
        ),
        model=resolved_model,
        temperature=temperature,
        persona=persona,
        # No skills — loading any SDK skill causes load_sdk_skills() to also load
        # pdf-tools and memory-scratchpad, which confuse the model when it tries
        # to read document files instead of using the injected text context.
    )
