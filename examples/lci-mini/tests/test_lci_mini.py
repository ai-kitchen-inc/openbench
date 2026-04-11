"""Tests for the lci-mini example.

These tests verify the Persona Layer wiring without making any real LLM
calls — they check that the persona files load correctly, that BaseAgent
composes them into a single system prompt, and that Lici's identity
surfaces in the first memory message.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lci_mini import create_lici_agent, get_persona_dir

from openbench.intelligence import BaseAgent, Persona
from openbench.intelligence.base import MessageRole

# ---------------------------------------------------------------------------
# Persona files on disk
# ---------------------------------------------------------------------------


def test_persona_dir_exists():
    d = get_persona_dir()
    assert d.is_dir(), f"Persona directory missing: {d}"


@pytest.mark.parametrize("filename", ["SOUL.md", "STYLE.md", "AGENTS.md"])
def test_persona_files_present(filename):
    f = get_persona_dir() / filename
    assert f.exists(), f"{filename} not found in persona dir"
    assert f.stat().st_size > 0, f"{filename} is empty"


def test_soul_mentions_lici_identity():
    soul = (get_persona_dir() / "SOUL.md").read_text()
    assert "Lici" in soul
    assert "LCI" in soul or "Life Cycle" in soul


def test_style_defines_language():
    style = (get_persona_dir() / "STYLE.md").read_text()
    # Persona is bilingual with Bahasa Indonesia as default.
    assert "Indonesia" in style or "Bahasa" in style


def test_agents_defines_modes():
    agents = (get_persona_dir() / "AGENTS.md").read_text()
    assert "PROPER" in agents
    assert "Methodology" in agents or "Mode" in agents


# ---------------------------------------------------------------------------
# Persona loading via OpenBench SDK
# ---------------------------------------------------------------------------


def test_persona_from_dir_loads_all_sections():
    persona = Persona.from_dir(get_persona_dir())

    assert persona  # truthy — has content
    assert persona.soul, "SOUL section empty"
    assert persona.style, "STYLE section empty"
    assert persona.agents, "AGENTS section empty"

    summary = persona.summary()
    assert summary["soul_chars"] > 0
    assert summary["style_chars"] > 0
    assert summary["agents_chars"] > 0
    assert summary["total_chars"] == sum(
        (summary["soul_chars"], summary["style_chars"], summary["agents_chars"])
    ) + 2 * len("\n\n")


def test_persona_compose_preserves_order():
    persona = Persona.from_dir(get_persona_dir())
    composed = persona.compose()

    soul_idx = composed.index(persona.soul)
    style_idx = composed.index(persona.style)
    agents_idx = composed.index(persona.agents)

    # soul -> style -> agents order is fixed in Persona.compose()
    assert soul_idx < style_idx < agents_idx


def test_persona_source_points_to_soul_dir():
    persona = Persona.from_dir(get_persona_dir())
    assert Path(persona.source).name == "soul"


# ---------------------------------------------------------------------------
# Agent factory (no real LLM call)
# ---------------------------------------------------------------------------


def test_create_lici_agent_requires_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        create_lici_agent()


def test_create_lici_agent_wires_persona(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    assert isinstance(agent, BaseAgent)
    assert agent.model == "gemini-2.5-flash"
    assert agent.temperature == 0.3

    # Persona was loaded from disk and stored on the agent.
    assert agent._persona is not None
    assert agent._persona.soul, "SOUL.md not loaded into agent"
    assert agent._persona.style, "STYLE.md not loaded into agent"
    assert agent._persona.agents, "AGENTS.md not loaded into agent"


def test_agent_system_prompt_is_composed_persona(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    composed = agent._persona.compose()
    assert agent._system_prompt == composed

    # First memory message is the system message carrying the persona.
    assert agent.memory.messages
    first = agent.memory.messages[0]
    assert first.role == MessageRole.SYSTEM
    assert first.content == composed
    assert "Lici" in first.content
    assert "PROPER" in first.content


def test_agent_accepts_api_key_parameter():
    agent = create_lici_agent(api_key="explicit-test-key")
    assert isinstance(agent, BaseAgent)
    assert agent._persona is not None


# ---------------------------------------------------------------------------
# FastAPI app (server mode)
# ---------------------------------------------------------------------------


def test_fastapi_app_creates_successfully(monkeypatch):
    """create_app() should wire persona + ChatEngine + AG-UI handler."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")

    from fastapi import FastAPI
    from lci_mini.server.app import create_app

    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "LCI Mini — Persona Layer Demo"

    routes = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/awp" in routes
    assert "/chat/action" in routes
    assert "/persona" in routes
    assert "/health" in routes


def test_persona_endpoint_exposes_composed_prompt(monkeypatch):
    """/persona should return the composed persona summary + contents."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")

    from fastapi.testclient import TestClient
    from lci_mini.server.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/persona")
        assert resp.status_code == 200
        data = resp.json()

        assert data["loaded"] is True
        assert data["soul_chars"] > 0
        assert data["style_chars"] > 0
        assert data["agents_chars"] > 0
        assert "Lici" in data["soul"]
        assert "PROPER" in data["agents"]
