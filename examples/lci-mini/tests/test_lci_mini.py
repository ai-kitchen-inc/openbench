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
    assert app.title == "LCI Mini — Persona + Skill Layer Demo"

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
# Skill Layer integration — XQL (Excel-as-RDBMS)
# ---------------------------------------------------------------------------


def test_skills_dir_exists():
    from lci_mini import get_skills_dir

    d = get_skills_dir()
    assert d.is_dir(), f"Skills directory missing: {d}"


def test_xql_skill_package_present():
    from lci_mini import get_skills_dir

    xql_dir = get_skills_dir() / "xql"
    assert xql_dir.is_dir()
    assert (xql_dir / "SKILL.md").exists()
    assert (xql_dir / "tools.py").exists()
    assert (xql_dir / "config" / "aliases.yaml").exists()
    assert (xql_dir / "config" / "units.yaml").exists()
    assert (xql_dir / "config" / "lci_rules.yaml").exists()
    assert (xql_dir / "references" / "grouping-rules.md").exists()


def test_get_skill_paths_returns_xql():
    from lci_mini import get_skill_paths

    paths = get_skill_paths()
    assert len(paths) == 1
    assert any("xql" in p for p in paths)


# A catalog of primitives the agent should have at its disposal.
_EXPECTED_XQL_TOOLS = {
    "xql_catalog",
    "xql_list_tables",
    "xql_describe_table",
    "xql_select",
    "xql_project",
    "xql_where",
    "xql_order",
    "xql_distinct",
    "xql_group",
    "xql_pareto",
    "xql_join",
    "xql_union",
    "xql_pivot",
    "xql_build_io_table",
}


def test_create_lici_agent_loads_xql_skill(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    assert agent._skill_registry is not None
    names = {s.name for s in agent._skill_registry.all()}
    assert names == {"xql"}

    # Every XQL primitive is registered on the agent's ToolExecutor
    for tool_name in _EXPECTED_XQL_TOOLS:
        assert tool_name in agent.tools._tools, f"missing {tool_name}"


def test_agent_system_prompt_contains_persona_and_xql(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()

    prompt = agent._system_prompt
    assert "Lici" in prompt  # from persona
    assert "# Skill: xql" in prompt  # from skill registry
    assert "XQL" in prompt  # from SKILL.md
    assert "xql_pareto" in prompt  # primitives mentioned
    assert "Grouping Rules" in prompt  # from references/grouping-rules.md

    # Persona precedes skill context
    assert prompt.index("Lici") < prompt.index("# Skill: xql")


def test_skills_endpoint_exposes_xql(monkeypatch):
    """/skills should return the single xql skill with 14 tools."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")

    from fastapi.testclient import TestClient
    from lci_mini.server.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()

        assert data["loaded"] is True
        assert data["summary"]["total"] == 1
        assert data["summary"]["total_tools"] == len(_EXPECTED_XQL_TOOLS)

        assert len(data["skills"]) == 1
        xql = data["skills"][0]
        assert xql["name"] == "xql"
        assert xql["has_tools"] is True
        assert set(xql["tools"]) == _EXPECTED_XQL_TOOLS
        assert "grouping-rules.md" in xql["references"]


# ---------------------------------------------------------------------------
# XQL end-to-end — exercise the primitives against a synthetic workbook
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_workbook(tmp_path):
    """Write a 6-row LCI workbook mirroring the Pertamina LDI shape."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "Proses": [
                "Refinery A",
                "Refinery A",
                "Refinery B",
                "Refinery B",
                "Boiler",
                "CSR Program",
            ],
            "Kategori": [
                "Bahan Bakar Cair",
                "Emisi Udara",
                "Bahan Bakar Cair",
                "Emisi Udara",
                "Fuel Gas",
                "Bahan Baku",
            ],
            "Nama Bahan/Alat": [
                "Diesel",
                "CO2",
                "Diesel",
                "CO2",
                "Natural Gas",
                "Paper",
            ],
            "I/O": ["Input", "Output", "Input", "Output", "Input", "Input"],
            "Unit": ["L", "kg", "L", "kg", "m3", "kg"],
            "Semberah EP": [1000.0, 50.0, 800.0, 40.0, 200.0, 5.0],
            "Produced From": ["Generator", "Stack", "Generator", "Stack", "Heater", "Office"],
        }
    )
    path = tmp_path / "testlci.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sheet14", index=False)
    return path


@pytest.fixture
def xql_agent(monkeypatch):
    """A Lici agent with xql preloaded and the catalog reset between tests."""
    import sys

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    agent = create_lici_agent()
    # Reset the xql module-level catalog so tests don't cross-contaminate.
    # SkillRegistry registers the tools module in sys.modules under a
    # namespaced key (openbench_skill_<name>); reach it from there.
    xql_module = sys.modules["openbench_skill_xql"]
    xql_module._reset_state()
    return agent


def test_xql_catalog_discovers_sheet(xql_agent, synthetic_workbook):
    result = xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    assert "testlci.Sheet14" in result["registered"]

    listed = xql_agent.tools.execute("xql_list_tables")
    assert listed["total"] == 1
    assert listed["tables"][0]["row_count"] == 6
    aliases = set(listed["tables"][0]["aliases"])
    # Alias registry should have resolved the Indonesian headers
    assert {"process", "category", "material", "amount"}.issubset(aliases)


def test_xql_where_filter_by_category(xql_agent, synthetic_workbook):
    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    result = xql_agent.tools.execute(
        "xql_where",
        table_id="testlci.Sheet14",
        conditions=[["category", "==", "Emisi Udara"]],
    )
    assert result["filtered_rows"] == 2
    for row in result["rows"]:
        assert row["Kategori"] == "Emisi Udara"


def test_xql_group_sum_by_process(xql_agent, synthetic_workbook):
    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    result = xql_agent.tools.execute(
        "xql_group",
        table_id="testlci.Sheet14",
        group_by=["process"],
        agg={"amount": "sum"},
    )
    totals = {row["Proses"]: row["Semberah EP_sum"] for row in result["rows"]}
    # Refinery A = 1000 (Diesel) + 50 (CO2) = 1050
    assert totals["Refinery A"] == 1050.0
    # Refinery B = 800 + 40 = 840
    assert totals["Refinery B"] == 840.0


def test_xql_distinct(xql_agent, synthetic_workbook):
    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    result = xql_agent.tools.execute(
        "xql_distinct",
        table_id="testlci.Sheet14",
        columns=["category"],
    )
    values = {row["Kategori"] for row in result["rows"]}
    assert values == {
        "Bahan Bakar Cair",
        "Emisi Udara",
        "Fuel Gas",
        "Bahan Baku",
    }


def test_xql_pareto_returns_hotspots_plus_rest(xql_agent, synthetic_workbook):
    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    result = xql_agent.tools.execute(
        "xql_pareto",
        table_id="testlci.Sheet14",
        group_by="material",
        value_col="amount",
        threshold=0.80,
    )
    assert result["hotspot_count"] >= 1
    # Diesel (1800) should dominate and therefore be a hotspot
    assert any(row.get("Nama Bahan/Alat") == "Diesel" for row in result["rows"])
    # Final cumulative share should always reach 1.0
    assert result["rows"][-1]["cumulative"] == pytest.approx(1.0)


def test_xql_build_io_table_excludes_csr(xql_agent, synthetic_workbook):
    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    result = xql_agent.tools.execute(
        "xql_build_io_table",
        source="testlci.Sheet14",
        products={"Crude": {"amount": 1000, "unit": "barrel"}},
        exclude_process=["CSR.*"],
    )
    category_names = {c["category"] for c in result["categories"]}
    # CSR Program owned the only "Bahan Baku" row — it must be excluded
    assert "Bahan Baku" not in category_names
    assert {"Bahan Bakar Cair", "Emisi Udara", "Fuel Gas"}.issubset(category_names)


def test_xql_order_desc(xql_agent, synthetic_workbook):
    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    result = xql_agent.tools.execute(
        "xql_order",
        table_id="testlci.Sheet14",
        by="amount",
        ascending=False,
    )
    amounts = [row["Semberah EP"] for row in result["rows"]]
    assert amounts == sorted(amounts, reverse=True)


# ---------------------------------------------------------------------------
# Upload flow — /chat/upload + /awp attachment resolution
# ---------------------------------------------------------------------------


def test_upload_then_catalog_via_contextvar(monkeypatch, tmp_path):
    """End-to-end: upload xlsx -> xql_catalog() (no args) picks it up."""
    import sys

    import pandas as pd
    from fastapi.testclient import TestClient

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("LCI_MINI_UPLOAD_DIR", str(tmp_path / "uploads"))

    from lci_mini.server.app import create_app

    # Build a tiny LCI workbook
    xlsx_path = tmp_path / "upload.xlsx"
    pd.DataFrame(
        {
            "Proses": ["A", "B"],
            "Kategori": ["x", "y"],
            "Nama Bahan/Alat": ["m1", "m2"],
            "Unit": ["kg", "kg"],
            "Semberah EP": [100.0, 200.0],
        }
    ).to_excel(xlsx_path, sheet_name="Sheet1", index=False)

    with TestClient(create_app()) as client:
        # Upload — should return an id we can feed back via /awp
        with xlsx_path.open("rb") as fh:
            resp = client.post(
                "/chat/upload",
                files={
                    "file": (
                        "upload.xlsx",
                        fh,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        assert resp.status_code == 200
        meta = resp.json()
        assert "id" in meta
        file_id = meta["id"]

        # Simulate the /awp handler wiring: server resolves id to disk path
        # and pushes it into the xql ContextVar. We skip the full /awp
        # AG-UI protocol (needs an LLM) and instead assert the wiring
        # callable exists and produces the right state.
        xql_mod = sys.modules["openbench_skill_xql"]

        # Replicate what /awp does: look up stored path, set ContextVar,
        # then call xql_catalog() with no args.
        from openbench.chat.files import FileStore

        store = FileStore(upload_dir=str(tmp_path / "uploads"))
        stored = store.get(file_id)
        assert stored is not None
        xql_mod.set_uploaded_files([stored.path])

        # Reset and catalog via the no-args path
        xql_mod._reset_state()
        xql_mod.set_uploaded_files([stored.path])
        result = xql_mod.xql_catalog()

        assert "error" not in result
        assert any(t.endswith(".Sheet1") for t in result["registered"])

        # Downstream query works
        table_id = result["registered"][0]
        rows = xql_mod.xql_where(table_id, conditions=[["amount", ">", 150]])
        assert rows["filtered_rows"] == 1


def test_xql_catalog_returns_error_when_no_files(monkeypatch):
    """xql_catalog() with no attachments should return a helpful error."""
    import sys

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    # Instantiate the agent so xql gets loaded into sys.modules
    create_lici_agent()

    xql_mod = sys.modules["openbench_skill_xql"]
    xql_mod._reset_state()
    xql_mod.set_uploaded_files(None)

    result = xql_mod.xql_catalog()
    assert result["registered"] == []
    assert "error" in result
    assert "attach" in result["error"].lower()
