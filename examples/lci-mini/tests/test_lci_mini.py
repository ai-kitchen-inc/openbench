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


def test_agent_system_prompt_starts_with_persona(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    persona_composed = agent._persona.compose()

    # System prompt begins with the persona (identity before capabilities)
    assert agent._system_prompt.startswith(persona_composed)

    # First memory message is the system message carrying the full prompt
    assert agent.memory.messages
    first = agent.memory.messages[0]
    assert first.role == MessageRole.SYSTEM
    assert first.content == agent._system_prompt
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


# ---------------------------------------------------------------------------
# Skill Layer integration (Milestone 2)
# ---------------------------------------------------------------------------


def test_skills_dir_exists():
    from lci_mini import get_skills_dir

    d = get_skills_dir()
    assert d.is_dir(), f"Skills directory missing: {d}"


@pytest.mark.parametrize("skill_name", ["proper-2025", "unit-converter"])
def test_skill_packages_have_skill_md(skill_name):
    from lci_mini import get_skills_dir

    skill_md = get_skills_dir() / skill_name / "SKILL.md"
    assert skill_md.exists(), f"{skill_name}/SKILL.md not found"
    assert skill_md.stat().st_size > 0


def test_get_skill_paths_returns_both():
    from lci_mini import get_skill_paths

    paths = get_skill_paths()
    assert len(paths) == 2
    assert any("proper-2025" in p for p in paths)
    assert any("unit-converter" in p for p in paths)


def test_create_lici_agent_loads_skills(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    # Registry exists and has both skills
    assert agent._skill_registry is not None
    names = {s.name for s in agent._skill_registry.all()}
    assert names == {"proper-2025", "unit-converter"}

    # Unit-converter tool is registered on the agent's ToolExecutor
    assert "convert_unit" in agent.tools._tools


def test_agent_system_prompt_contains_persona_and_skills(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    prompt = agent._system_prompt
    # Persona markers
    assert "Lici" in prompt
    # Skill markers
    assert "proper-2025" in prompt
    assert "unit-converter" in prompt
    assert "PROPER 2025" in prompt  # from tiers.md reference
    assert "convert_unit" in prompt  # from SKILL.md of unit-converter

    # Persona should come before skills in the composed prompt
    p_idx = prompt.index("Lici")
    s_idx = prompt.index("# Skill: proper-2025")
    assert p_idx < s_idx


def test_unit_converter_tool_callable(monkeypatch):
    """The convert_unit tool should be invokable via the agent's executor."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    result = agent.tools.execute("convert_unit", value=1, from_unit="ton", to_unit="kg")
    assert result == {"value": 1000.0, "unit": "kg"}

    result = agent.tools.execute("convert_unit", value=1, from_unit="MJ", to_unit="kWh")
    assert abs(result["value"] - 0.2777777777777778) < 1e-9


def test_skills_endpoint_exposes_loaded_skills(monkeypatch):
    """/skills should return both loaded skills with tool & reference counts."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")

    from fastapi.testclient import TestClient
    from lci_mini.server.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()

        assert data["loaded"] is True
        assert data["summary"]["total"] == 2
        assert data["summary"]["total_tools"] == 1

        by_name = {s["name"]: s for s in data["skills"]}
        assert set(by_name) == {"proper-2025", "unit-converter"}

        proper = by_name["proper-2025"]
        assert proper["has_tools"] is False
        assert proper["tools"] == []
        assert "tiers.md" in proper["references"]

        uc = by_name["unit-converter"]
        assert uc["has_tools"] is True
        assert uc["tools"] == ["convert_unit"]
