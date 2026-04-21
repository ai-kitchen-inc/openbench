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
    assert agent.model == "gemini-3-flash-preview"
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


def test_agent_with_scratchpad_loads_memory_scratchpad_skill(monkeypatch, tmp_path):
    """Passing scratchpad= should auto-load the memory-scratchpad SDK skill."""
    from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    pad = LocalMarkdownScratchpad(tmp_path)

    agent = create_lici_agent(scratchpad=pad)
    assert agent._scratchpad is pad

    skill_names = {s.name for s in agent._skill_registry.all()}
    assert "memory-scratchpad" in skill_names

    # The four scratchpad tools should be registered on the agent
    for tool_name in ("read_memory", "write_memory", "append_memory", "list_memory_keys"):
        assert tool_name in agent.tools._tools, f"missing {tool_name}"

    # And they should round-trip through the bound pad
    agent.tools.execute("write_memory", key="notes", content="hello")
    assert pad.read("notes") == "hello"
    assert agent.tools.execute("read_memory", key="notes") == "hello"


# ---------------------------------------------------------------------------
# FastAPI app (server mode)
# ---------------------------------------------------------------------------


def test_fastapi_app_creates_successfully(monkeypatch, tmp_path):
    """create_app() should wire persona + ChatEngine + AG-UI handler."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))

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
    # Session CRUD endpoints added in Phase 2 migration
    assert "/sessions" in routes
    assert "/sessions/{session_id}" in routes


class TestFailClosedAuth:
    """Protected endpoints must 401 when no auth config is set at all."""

    def test_sessions_returns_401_without_auth_config(self, monkeypatch, tmp_path):
        """No FIREBASE_PROJECT_ID, no OPENBENCH_AUTH_DISABLED → chat must fail closed."""
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))
        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)

        from fastapi.testclient import TestClient
        from lci_mini.server.app import create_app

        with TestClient(create_app()) as client:
            resp = client.get("/sessions")
            assert resp.status_code == 401

    def test_upload_returns_401_without_auth_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))
        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)

        from fastapi.testclient import TestClient
        from lci_mini.server.app import create_app

        with TestClient(create_app()) as client:
            resp = client.post(
                "/chat/upload",
                files={"file": ("x.txt", b"hello", "text/plain")},
            )
            assert resp.status_code == 401

    def test_persona_returns_401_without_auth_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))
        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)

        from fastapi.testclient import TestClient
        from lci_mini.server.app import create_app

        with TestClient(create_app()) as client:
            assert client.get("/persona").status_code == 401
            assert client.get("/skills").status_code == 401
            assert client.get("/auth/me").status_code == 401

    def test_awp_returns_401_without_auth_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))
        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)

        from fastapi.testclient import TestClient
        from lci_mini.server.app import create_app

        with TestClient(create_app()) as client:
            resp = client.post("/awp", json={})
            assert resp.status_code == 401

    def test_health_still_public(self, monkeypatch, tmp_path):
        """/health and / do not require auth — health checks need it."""
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / ".openbench"))
        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)

        from fastapi.testclient import TestClient
        from lci_mini.server.app import create_app

        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200


class TestStorageBackendSelection:
    """Cover the env-var-driven switch between Local and Drive backends."""

    def test_defaults_to_local_backend(self, monkeypatch):
        from lci_mini.server.app import _build_storage_backend

        from openbench import LocalStorageBackend

        monkeypatch.delenv("LCI_MINI_DRIVE_ROOT", raising=False)
        monkeypatch.delenv("LCI_MINI_STORAGE_ROOT", raising=False)
        monkeypatch.delenv("LCI_MINI_SERVICE_ACCOUNT", raising=False)

        backend, label = _build_storage_backend()
        assert isinstance(backend, LocalStorageBackend)
        assert label.startswith("Local(")

    def test_local_root_env_override(self, monkeypatch, tmp_path):
        from lci_mini.server.app import _build_storage_backend

        from openbench import LocalStorageBackend

        monkeypatch.delenv("LCI_MINI_DRIVE_ROOT", raising=False)
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "alt"))

        backend, label = _build_storage_backend()
        assert isinstance(backend, LocalStorageBackend)
        assert str(tmp_path / "alt") in label

    def test_drive_env_selects_drive_backend(self, monkeypatch):
        from lci_mini.server.app import _build_storage_backend

        from openbench.integrations.gdrive import GoogleDriveStorageBackend

        monkeypatch.setenv("LCI_MINI_DRIVE_ROOT", "folder-xyz")
        monkeypatch.setenv("LCI_MINI_SERVICE_ACCOUNT", "/fake/creds.json")

        backend, label = _build_storage_backend()
        assert isinstance(backend, GoogleDriveStorageBackend)
        assert backend.root_folder_id == "folder-xyz"
        assert "folder-xyz" in label

    def test_drive_without_service_account_raises(self, monkeypatch):
        from lci_mini.server.app import _build_storage_backend

        monkeypatch.setenv("LCI_MINI_DRIVE_ROOT", "folder-xyz")
        monkeypatch.delenv("LCI_MINI_SERVICE_ACCOUNT", raising=False)

        with pytest.raises(RuntimeError, match="LCI_MINI_SERVICE_ACCOUNT"):
            _build_storage_backend()


def test_sessions_endpoints_use_local_storage_backend(monkeypatch, tmp_path):
    """Phase 2 wiring: /sessions reads from the LocalStorageBackend SQLite store."""
    from fastapi.testclient import TestClient
    from lci_mini.server.app import create_app

    from openbench.chat.session import ChatSession
    from openbench.chat.stores.sqlite import SQLiteSessionStore

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
    storage_root = tmp_path / ".openbench"
    monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(storage_root))

    # Pre-seed the SQLite session store so /sessions has something to return
    store = SQLiteSessionStore(str(storage_root / "sessions.db"))
    session = ChatSession(session_id="s-seeded", title="Preseeded")
    session.add_user_message("ingat persona ini")
    store.save(session)

    with TestClient(create_app()) as client:
        # GET /sessions
        resp = client.get("/sessions")
        assert resp.status_code == 200
        summaries = resp.json()
        assert any(s["sessionId"] == "s-seeded" for s in summaries)

        # GET /sessions/{id}
        resp = client.get("/sessions/s-seeded")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Preseeded"
        assert len(data["messages"]) == 1

        # GET /sessions/unknown -> 404
        resp = client.get("/sessions/does-not-exist")
        assert resp.status_code == 404

        # DELETE /sessions/{id}
        resp = client.delete("/sessions/s-seeded")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = client.get("/sessions/s-seeded")
        assert resp.status_code == 404


def test_persona_endpoint_exposes_composed_prompt(monkeypatch):
    """/persona should return the composed persona summary + contents."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")

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
    # xql is the project skill; SDK skills (data-context-extractor,
    # data-visualization, export-excel, query-explorer) are auto-
    # discovered by SkillRegistry.load_sdk_skills().
    assert "xql" in names
    assert len(names) >= 1  # at minimum xql; SDK skills may also be present

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
    """/skills should include xql + any auto-discovered SDK skills."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")

    from fastapi.testclient import TestClient
    from lci_mini.server.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()

        assert data["loaded"] is True
        # At least xql + SDK skills
        assert data["summary"]["total"] >= 1
        assert data["summary"]["total_tools"] >= len(_EXPECTED_XQL_TOOLS)

        skill_names = {s["name"] for s in data["skills"]}
        assert "xql" in skill_names

        xql = next(s for s in data["skills"] if s["name"] == "xql")
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
            "Amount": [1000.0, 50.0, 800.0, 40.0, 200.0, 5.0],
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
    totals = {row["Proses"]: row["Amount_sum"] for row in result["rows"]}
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
    amounts = [row["Amount"] for row in result["rows"]]
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
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
    # Uploads now route through the per-user storage backend, which in
    # auth-disabled mode roots at LCI_MINI_STORAGE_ROOT/uploads/. Point
    # both env vars at the tmp path so the static-mount (legacy module-
    # level file_store) and the new per-user store land in the same dir.
    monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path))
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
            "Amount": [100.0, 200.0],
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
        # then call xql_catalog() with no args. With LCI_MINI_STORAGE_ROOT
        # set above, the per-user LocalStorageBackend roots at tmp_path
        # so uploads land at tmp_path/uploads/.
        from openbench.chat.files import LocalFileStore

        store = LocalFileStore(upload_dir=str(tmp_path / "uploads"))
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


def test_awp_recatalogs_from_prior_session_attachments(monkeypatch, tmp_path):
    """Agent cache TTL + skill re-import clears XQL _STATE. When the user
    sends a follow-up turn without re-attaching the file, /awp must still
    pre-warm the catalog from attachments recorded in prior session
    messages — otherwise the agent would hallucinate "connection lost"
    and ask the user to upload again."""
    import sys

    import pandas as pd
    from fastapi.testclient import TestClient
    from lci_mini.server.handler import LiciAGUIHandler

    from openbench.chat.session import Attachment, ChatSession

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
    monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("LCI_MINI_UPLOAD_DIR", str(tmp_path / "uploads"))

    from lci_mini.server.app import create_app

    xlsx_path = tmp_path / "prior_upload.xlsx"
    pd.DataFrame(
        {
            "Proses": ["A", "B"],
            "Kategori": ["x", "y"],
            "Nama Bahan/Alat": ["m1", "m2"],
            "Unit": ["kg", "kg"],
            "Amount": [100.0, 200.0],
        }
    ).to_excel(xlsx_path, sheet_name="Sheet1", index=False)

    # Short-circuit the AG-UI handler so the test doesn't need a real LLM.
    async def _noop_handle(self, request):
        from fastapi.responses import Response

        return Response(status_code=200)

    monkeypatch.setattr(LiciAGUIHandler, "handle", _noop_handle)

    with TestClient(create_app()) as client:
        # 1. Upload (turn 1 — file gets registered in the user's file store)
        with xlsx_path.open("rb") as fh:
            resp = client.post(
                "/chat/upload",
                files={
                    "file": (
                        "prior_upload.xlsx",
                        fh,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        assert resp.status_code == 200
        file_id = resp.json()["id"]

        # 2. Seed the session store with a prior user message that carried
        #    the attachment — this is what the AG-UI handler would write
        #    on the real turn-1 request.
        thread_id = "thread-recatalog-test"
        from lci_mini.server.request_scope import local_backend_for_uid

        storage = local_backend_for_uid("dev")
        session_store = storage.session_store()
        session = ChatSession(session_id=thread_id)
        session.add_user_message(
            "Analisis file saya",
            attachments=[
                Attachment(
                    id=file_id,
                    type="file",
                    name="prior_upload.xlsx",
                    url=f"/uploads/{file_id}",
                    mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                )
            ],
        )
        session_store.save(session)

        # 3. Reset catalog so we can prove the /awp handler re-populated it.
        #    Note: the agent build inside /awp may re-import the skill under
        #    the same sys.modules name, replacing this module object. Always
        #    re-fetch from sys.modules when asserting.
        sys.modules["openbench_skill_xql"]._reset_state()

        # 4. Turn 2 — NO new attachments, but threadId matches the session.
        resp = client.post(
            "/awp",
            json={"threadId": thread_id, "messages": [], "forwardedProps": {}},
        )
        assert resp.status_code == 200

        # 5. Catalog must now contain the sheet from the prior attachment.
        xql_mod_post = sys.modules["openbench_skill_xql"]
        state = getattr(xql_mod_post, "_STATE", {})
        assert any(k.endswith(".Sheet1") for k in state), (
            "Expected XQL _STATE to be pre-warmed from prior-message "
            f"attachment; got keys={list(state.keys())}"
        )


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


# ---------------------------------------------------------------------------
# Gemini-shaped JSON schema validation for XQL tool schemas
# ---------------------------------------------------------------------------
#
# Gemini function calling validates tool schemas against an OpenAPI 3.0
# subset. The two rejection reasons we hit live:
#   1. arrays missing `items`
#   2. nested arrays missing inner `items` (items.items)
#
# These tests walk every XQL_*_SCHEMA at test time and enforce the same
# constraints Gemini does, so schema bugs fail fast in CI instead of at
# runtime when a user makes their first chat request.


def _collect_xql_schemas() -> dict:
    """Import the xql skill module and return every XQL_*_SCHEMA constant."""
    import os
    import sys

    # Creating a Lici agent loads the xql skill module into sys.modules
    # under its namespaced key (openbench_skill_xql).
    os.environ.setdefault("GOOGLE_API_KEY", "fake-test-key")
    create_lici_agent()

    xql_mod = sys.modules["openbench_skill_xql"]
    return {
        name: getattr(xql_mod, name)
        for name in dir(xql_mod)
        if name.startswith("XQL_") and name.endswith("_SCHEMA")
    }


def _walk_schema(node, path: str, errors: list[str]) -> None:
    """Walk a JSON-schema-ish node and append any Gemini violations.

    Rules enforced:
        * Every "array" type must have a top-level "items" that itself has "type".
        * Every "items" that is an array must recursively have its own "items".
        * Every "object" type should have "properties" (empty dict OK) — free-form
          objects without properties are a known Gemini rejection path even when
          it sometimes tolerates them.
        * Every property in "properties" must declare a "type".
    """
    if not isinstance(node, dict):
        return

    node_type = node.get("type")

    if node_type == "array":
        items = node.get("items")
        if items is None:
            errors.append(f"{path}: array missing 'items'")
        else:
            if not isinstance(items, dict):
                errors.append(f"{path}.items: not a dict")
            elif "type" not in items:
                errors.append(f"{path}.items: missing 'type'")
            else:
                _walk_schema(items, f"{path}.items", errors)

    if node_type == "object":
        props = node.get("properties")
        add_props = node.get("additionalProperties")
        if props is None and add_props is None:
            errors.append(f"{path}: object missing 'properties' or 'additionalProperties'")
        if isinstance(props, dict):
            for pname, pnode in props.items():
                if not isinstance(pnode, dict):
                    errors.append(f"{path}.properties.{pname}: not a dict")
                    continue
                if "type" not in pnode:
                    errors.append(f"{path}.properties.{pname}: missing 'type'")
                _walk_schema(pnode, f"{path}.properties.{pname}", errors)


def _schema_violations(schema: dict, name: str) -> list[str]:
    """Return a list of Gemini violations in a function-schema dict."""
    errors: list[str] = []
    fn = schema.get("function", {})
    params = fn.get("parameters")
    if params is None:
        return [f"{name}: missing function.parameters"]
    _walk_schema(params, f"{name}.parameters", errors)
    return errors


@pytest.mark.parametrize("schema_name", sorted(_collect_xql_schemas().keys()))
def test_xql_schema_is_gemini_valid(schema_name):
    """Every XQL tool schema must pass Gemini's OpenAPI 3.0 subset checks."""
    schemas = _collect_xql_schemas()
    schema = schemas[schema_name]
    violations = _schema_violations(schema, schema_name)
    assert violations == [], (
        f"{schema_name} has schema bugs that Gemini would reject:\n  - " + "\n  - ".join(violations)
    )


def test_all_xql_schemas_have_required_fields():
    """Every XQL schema must declare function.name, description, parameters."""
    schemas = _collect_xql_schemas()
    assert schemas, "No XQL_*_SCHEMA constants found — is xql loaded?"
    for name, schema in schemas.items():
        assert schema.get("type") == "function", f"{name}: wrong top-level type"
        fn = schema.get("function", {})
        assert fn.get("name"), f"{name}: missing function.name"
        assert fn.get("description"), f"{name}: missing function.description"
        assert "parameters" in fn, f"{name}: missing function.parameters"


# ---------------------------------------------------------------------------
# Render-items pattern — tools push {headers, rows, title} to ContextVar queue
# ---------------------------------------------------------------------------


def test_xql_tools_push_render_items(xql_agent, synthetic_workbook):
    """Query tools should push table-shaped items to the render queue.

    Verifies the lci-ignite-x pattern: tool returns data to LLM and ALSO
    pushes a {headers, rows, title} item that chat-ui's TableRenderer
    can pick up and emit as an ObTable component.
    """
    import sys

    xql_mod = sys.modules["openbench_skill_xql"]
    xql_mod.clear_render_items()

    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    xql_agent.tools.execute(
        "xql_where",
        table_id="testlci.Sheet14",
        conditions=[["category", "==", "Bahan Bakar Cair"]],
    )

    items = xql_mod.get_render_items()
    # Expect at least one table item from xql_where
    assert len(items) >= 1
    last = items[-1]
    assert "headers" in last and len(last["headers"]) > 0
    assert "rows" in last and isinstance(last["rows"], list)
    assert "title" in last
    assert "WHERE" in last["title"]
    # headers match the original Excel columns
    assert "Proses" in last["headers"] or "process" in last["headers"]


def test_render_items_shape_matches_table_renderer(xql_agent, synthetic_workbook):
    """Pushed items must satisfy chat-ui's TableRenderer.detect() contract.

    TableRenderer expects dict with non-empty 'headers' list and 'rows' list.
    """
    import sys

    from openbench.chat.renderers.table import TableRenderer

    xql_mod = sys.modules["openbench_skill_xql"]
    xql_mod.clear_render_items()

    xql_agent.tools.execute("xql_catalog", files=[str(synthetic_workbook)])
    xql_agent.tools.execute(
        "xql_pareto",
        table_id="testlci.Sheet14",
        group_by="material",
        value_col="amount",
        threshold=0.80,
    )

    items = xql_mod.get_render_items()
    assert items, "xql_pareto did not push any render item"

    renderer = TableRenderer()
    for item in items:
        assert renderer.detect(item), (
            f"TableRenderer rejected: {list(item.keys())} — "
            f"headers type: {type(item.get('headers')).__name__}, "
            f"rows type: {type(item.get('rows')).__name__}"
        )


def test_server_wires_render_items_fn(monkeypatch):
    """create_app should hook ChatEngine's render_items_fn to xql's getter."""
    import sys

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")

    from lci_mini.server.app import create_app

    app = create_app()
    # create_app stores the engine on the agui_handler — poke into it
    # via the /skills endpoint which already has an agent reference.
    # Simpler: check that the xql module exposes the getters we need.
    xql_mod = sys.modules["openbench_skill_xql"]
    assert callable(getattr(xql_mod, "get_render_items", None))
    assert callable(getattr(xql_mod, "clear_render_items", None))

    # Smoke test: clear and verify empty
    xql_mod.clear_render_items()
    assert xql_mod.get_render_items() == []

    # The /skills route should still work (no regression from wiring)
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.get("/skills")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Memory sanitization — repair orphaned tool turns
# ---------------------------------------------------------------------------


def _msg(role, content="", tool_calls=None, tool_call_id=None, name=None):
    """Tiny helper to build Message objects for tests."""
    from openbench.intelligence.base import Message, MessageRole

    return Message(
        role=MessageRole[role.upper()],
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        name=name,
    )


class TestSanitizeMessages:
    def test_empty_list_passes_through(self):
        from lci_mini.server.handler import sanitize_messages

        assert sanitize_messages([]) == []

    def test_valid_conversation_preserved(self):
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("system", "You are Lici"),
            _msg("user", "halo"),
            _msg("assistant", "halo juga"),
            _msg("user", "tampilkan data"),
            _msg(
                "assistant",
                "",
                tool_calls=[{"id": "c0", "name": "xql_catalog", "arguments": {}}],
            ),
            _msg("tool", '{"ok": true}', tool_call_id="c0", name="xql_catalog"),
            _msg("assistant", "selesai"),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == len(msgs)

    def test_orphaned_assistant_tool_calls_dropped(self):
        """assistant(tool_calls) without following tool(result) is dropped."""
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("system", "sys"),
            _msg("user", "q1"),
            _msg(
                "assistant",
                "",
                tool_calls=[{"id": "c0", "name": "xql_catalog", "arguments": {}}],
            ),
            # tool response missing!
            _msg("user", "q2"),
        ]
        result = sanitize_messages(msgs)
        roles = [m.role.value for m in result]
        # Orphan assistant removed, two users collapse to last
        assert roles == ["system", "user"]
        assert result[-1].content == "q2"

    def test_orphaned_tool_result_dropped(self):
        """tool(result) without preceding assistant(tool_calls) is dropped."""
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("system", "sys"),
            _msg("user", "q1"),
            _msg("tool", '{"stale": true}', tool_call_id="c0", name="xql_catalog"),
            _msg("assistant", "ok"),
        ]
        result = sanitize_messages(msgs)
        roles = [m.role.value for m in result]
        assert "tool" not in roles
        assert roles == ["system", "user", "assistant"]

    def test_consecutive_users_collapsed(self):
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("user", "q1"),
            _msg("user", "q2"),
            _msg("user", "q3"),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].content == "q3"

    def test_consecutive_assistants_collapsed(self):
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("user", "q"),
            _msg("assistant", "a1"),
            _msg("assistant", "a2"),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 2
        assert result[-1].content == "a2"

    def test_assistant_with_partial_tool_responses_dropped(self):
        """Assistant with 2 tool calls but only 1 tool response — drop the lot."""
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("system", "sys"),
            _msg("user", "q"),
            _msg(
                "assistant",
                "",
                tool_calls=[
                    {"id": "c0", "name": "xql_catalog", "arguments": {}},
                    {"id": "c1", "name": "xql_list_tables", "arguments": {}},
                ],
            ),
            _msg("tool", '{"ok": 1}', tool_call_id="c0", name="xql_catalog"),
            # second tool response missing!
            _msg("user", "retry"),
        ]
        result = sanitize_messages(msgs)
        roles = [m.role.value for m in result]
        assert "tool" not in roles
        # Assistant + both tool responses dropped; users collapse
        assert roles == ["system", "user"]
        assert result[-1].content == "retry"

    def test_multiple_valid_tool_cycles_preserved(self):
        """Multi-iteration tool loops should survive sanitization."""
        from lci_mini.server.handler import sanitize_messages

        msgs = [
            _msg("system", "sys"),
            _msg("user", "build io"),
            _msg(
                "assistant",
                "",
                tool_calls=[{"id": "c0", "name": "xql_catalog", "arguments": {}}],
            ),
            _msg("tool", '{"ok": 1}', tool_call_id="c0", name="xql_catalog"),
            _msg(
                "assistant",
                "",
                tool_calls=[{"id": "c0", "name": "xql_pareto", "arguments": {}}],
            ),
            _msg("tool", '{"rows": []}', tool_call_id="c0", name="xql_pareto"),
            _msg("assistant", "done"),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == len(msgs)


# ---------------------------------------------------------------------------
# BaseAgent rollback on iteration failure
# ---------------------------------------------------------------------------


def test_base_agent_rolls_back_partial_tool_turn_on_failure():
    """Exception during tool execution must NOT leave orphaned tool_calls."""
    from unittest.mock import MagicMock

    from openbench.intelligence.base import AgentMemory, BaseAgent

    agent = BaseAgent(goal="test", system_prompt="sys")
    agent.memory = AgentMemory()
    agent.memory.add_system("sys")
    agent.memory.add_user("do thing")

    # Mock the LLM to return a tool call once, then fail if called again
    mock_llm = MagicMock()
    tool_response = MagicMock()
    tool_response.text = ""
    tool_response.tool_calls = [MagicMock(id="c0")]
    tool_response.tool_calls[0].function = MagicMock(name="xql_catalog")
    tool_response.tool_calls[0].function.name = "xql_catalog"
    tool_response.tool_calls[0].function.arguments = "{}"
    tool_response.tokens_used = 0
    tool_response.cost = 0.0
    tool_response.metadata = {}
    tool_response.raw_content = None
    mock_llm.generate.return_value = tool_response
    agent._llm = mock_llm

    # Sabotage memory.add_tool_result so it explodes after add_assistant succeeds
    def boom(*args, **kwargs):
        raise RuntimeError("simulated SQLite failure")

    agent.memory.add_tool_result = boom

    # Register a passing tool so execute() gets past tool invocation itself
    agent.tools.register("xql_catalog", lambda: {"ok": True})

    from openbench.core.abstractions import ExecutionContext

    result = agent.execute(ExecutionContext(goal="do thing"))
    assert result.status == "failed"
    assert "simulated SQLite failure" in result.metadata["error"]

    # Critical: memory must NOT contain the orphaned assistant(tool_calls)
    orphan = [m for m in agent.memory.messages if m.role.value == "assistant" and m.tool_calls]
    assert orphan == [], f"rollback failed — found orphan: {orphan}"
