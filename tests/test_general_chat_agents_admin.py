"""Tests for the /admin/agents CRUD endpoints."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

pytestmark = pytest.mark.integration


class _AppHarness(unittest.TestCase):
    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(self.tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(self.tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(self.tmpdir / "downloads"),
                    "GENERAL_CHAT_MEMORY_DB": str(self.tmpdir / "memory.db"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        environ.pop("GENERAL_CHAT_LOCAL_GROUP", None)

        def _fresh_agent(**kwargs):
            agent = Mock()
            agent.model = kwargs.get("model") or "mock-model"
            agent._persona = None
            agent._skill_registry = None
            return agent

        stack.enter_context(patch("general_chat.server.app.create_agent", side_effect=_fresh_agent))
        # create_app wires module-global option providers to this app's
        # catalog cache — reset them so later tests see the defaults.
        from general_chat.runtime_settings import (
            set_embedding_options_provider,
            set_model_options_provider,
        )

        self.addCleanup(set_model_options_provider, None)
        self.addCleanup(set_embedding_options_provider, None)
        from general_chat.server.app import create_app

        return TestClient(create_app())


class TestAgentAdminCrud(_AppHarness):
    def test_crud_round_trip(self):
        client = self._client()
        created = client.post(
            "/admin/agents",
            json={
                "name": "Analis Keuangan",
                "description": "Laporan keuangan, anggaran, pajak.",
                "model": "gemini-2.5-pro",
                "skills": ["query-explorer"],
            },
        )
        self.assertEqual(created.status_code, 201)
        payload = created.json()
        self.assertEqual(payload["id"], "analis-keuangan")
        self.assertEqual(payload["model"], "gemini-2.5-pro")
        self.assertEqual(payload["skills"], ["query-explorer"])
        self.assertTrue(payload["enabled"])

        listed = client.get("/admin/agents").json()["agents"]
        self.assertEqual([agent["id"] for agent in listed], ["analis-keuangan"])

        fetched = client.get("/admin/agents/analis-keuangan")
        self.assertEqual(fetched.status_code, 200)

        updated = client.put(
            "/admin/agents/analis-keuangan",
            json={"description": "Analisis keuangan dan pajak.", "temperature": 0.1},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["description"], "Analisis keuangan dan pajak.")
        self.assertEqual(updated.json()["temperature"], 0.1)

        deleted = client.delete("/admin/agents/analis-keuangan")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get("/admin/agents").json()["agents"], [])
        self.assertEqual(client.get("/admin/agents/analis-keuangan").status_code, 404)

    def test_duplicate_conflict(self):
        client = self._client()
        body = {"name": "HR Bot", "description": "SDM."}
        self.assertEqual(client.post("/admin/agents", json=body).status_code, 201)
        self.assertEqual(client.post("/admin/agents", json=body).status_code, 409)

    def test_admin_only(self):
        client = self._client()
        headers = {"X-Local-Role": "user"}
        self.assertEqual(client.get("/admin/agents", headers=headers).status_code, 403)
        self.assertEqual(
            client.post(
                "/admin/agents", json={"name": "x", "description": "y"}, headers=headers
            ).status_code,
            403,
        )

    def test_validation_errors(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})

        no_name = client.post("/admin/agents", json={"description": "x"})
        self.assertEqual(no_name.status_code, 400)

        bad_model = client.post(
            "/admin/agents",
            json={"name": "B", "description": "d", "model": "gpt-nonexistent"},
        )
        self.assertEqual(bad_model.status_code, 400)

        bad_skill = client.post(
            "/admin/agents",
            json={"name": "C", "description": "d", "skills": ["not-a-skill"]},
        )
        self.assertEqual(bad_skill.status_code, 400)

        bad_custom = client.post(
            "/admin/agents",
            json={"name": "D", "description": "d", "customSkillIds": ["ghost"]},
        )
        self.assertEqual(bad_custom.status_code, 400)

        self_escalation = client.put("/admin/agents/analis", json={"escalationAgentId": "analis"})
        self.assertEqual(self_escalation.status_code, 400)

        ghost_escalation = client.put("/admin/agents/analis", json={"escalationAgentId": "ghost"})
        self.assertEqual(ghost_escalation.status_code, 400)

        # An enabled agent must keep a router-usable description.
        blank_description = client.put("/admin/agents/analis", json={"description": " "})
        self.assertEqual(blank_description.status_code, 400)
        # Disabling first makes a blank description acceptable.
        disabled = client.put("/admin/agents/analis", json={"description": "", "enabled": False})
        self.assertEqual(disabled.status_code, 200)

    def test_escalation_wiring_and_delete_cascade(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Senior", "description": "Konsultan."})
        client.post(
            "/admin/agents",
            json={
                "name": "Junior",
                "description": "Analis.",
                "escalationAgentId": "senior",
                "confidenceThreshold": 0.7,
            },
        )
        junior = client.get("/admin/agents/junior").json()
        self.assertEqual(junior["escalationAgentId"], "senior")
        self.assertEqual(junior["confidenceThreshold"], 0.7)

        client.delete("/admin/agents/senior")
        junior = client.get("/admin/agents/junior").json()
        self.assertEqual(junior["escalationAgentId"], "")

    def test_options_payload(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Senior", "description": "Konsultan."})
        options = client.get("/admin/agents/options").json()
        self.assertIn("gemini-2.5-pro", options["models"])
        self.assertIn("query-explorer", options["sdkSkills"])
        self.assertIn("export-excel", options["sdkSkills"])
        self.assertEqual(options["escalationTargets"], [{"id": "senior", "name": "Senior"}])
        self.assertEqual(options["defaults"]["confidenceThreshold"], 0.5)
        template_ids = [template["id"] for template in options["personaTemplates"]]
        self.assertIn("soft-grounded", template_ids)
        self.assertIn("strict", template_ids)
        for template in options["personaTemplates"]:
            for key in ("name", "description", "soul", "style", "agents", "goal"):
                self.assertIn(key, template)

    def test_update_invalidates_registry_cache(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})
        registry = client.app.state.agent_registry
        first = registry.get("analis")
        self.assertIsNotNone(first)
        client.put("/admin/agents/analis", json={"description": "Baru."})
        second = registry.get("analis")
        self.assertIsNot(first, second)

    def test_mcp_server_ids_saved_and_validated(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})
        # The registry always contains the internal OpenBench server.
        options = client.get("/admin/agents/options").json()
        server_ids = [server["id"] for server in options["mcpServers"]]
        self.assertIn("internal-openbench", server_ids)

        saved = client.put(
            "/admin/agents/analis", json={"mcpServerIds": ["internal-openbench"]}
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["mcpServerIds"], ["internal-openbench"])

        rejected = client.put(
            "/admin/agents/analis", json={"mcpServerIds": ["tidak-ada"]}
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("tidak-ada", rejected.json()["detail"])

    def test_profile_build_attaches_selected_mcp_servers(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})
        client.put("/admin/agents/analis", json={"mcpServerIds": ["internal-openbench"]})
        with patch(
            "general_chat.server.app.reload_external_mcp_tools"
        ) as reload_mock:
            agent = client.app.state.agent_registry.get("analis")
        self.assertIsNotNone(agent)
        reload_mock.assert_called_once()
        called_agent = reload_mock.call_args.args[0]
        self.assertIs(called_agent, agent)
        self.assertEqual(
            reload_mock.call_args.kwargs["server_ids"], {"internal-openbench"}
        )

    def test_profile_build_skips_mcp_attach_without_selection(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})
        with patch(
            "general_chat.server.app.reload_external_mcp_tools"
        ) as reload_mock:
            self.assertIsNotNone(client.app.state.agent_registry.get("analis"))
        reload_mock.assert_not_called()

    def test_guardrails_saved_and_validated(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})
        saved = client.put(
            "/admin/agents/analis", json={"guardrails": "Hanya topik keuangan."}
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["guardrails"], "Hanya topik keuangan.")

        self.assertEqual(
            client.put("/admin/agents/analis", json={"guardrails": 123}).status_code, 400
        )
        self.assertEqual(
            client.put(
                "/admin/agents/analis", json={"guardrails": "x" * 8001}
            ).status_code,
            400,
        )

    def test_guardrails_composed_before_confidence_protocol(self):
        client = self._client()
        client.post("/admin/agents", json={"name": "Senior", "description": "Konsultan."})
        client.post("/admin/agents", json={"name": "Analis", "description": "Keuangan."})
        client.put(
            "/admin/agents/analis",
            json={
                "guardrails": "Hanya jawab topik keuangan.",
                "escalationAgentId": "senior",
            },
        )

        from general_chat.server import app as app_module
        from openbench.intelligence.protocol import CONFIDENCE_PROTOCOL_PROMPT

        captured: dict = {}
        real = app_module.persona_from_settings

        def spy(value):
            captured["value"] = value
            return real(value)

        with patch("general_chat.server.app.persona_from_settings", side_effect=spy):
            self.assertIsNotNone(client.app.state.agent_registry.get("analis"))

        agents_text = captured["value"]["agents"]
        self.assertIn("## Guardrails (Agen)", agents_text)
        self.assertIn("Hanya jawab topik keuangan.", agents_text)
        # The escalation marker instruction must stay last in the rules.
        protocol_head = CONFIDENCE_PROTOCOL_PROMPT.strip()[:40]
        self.assertLess(
            agents_text.index("## Guardrails (Agen)"), agents_text.index(protocol_head)
        )
        self.assertTrue(
            agents_text.rstrip().endswith(CONFIDENCE_PROTOCOL_PROMPT.strip())
        )


if __name__ == "__main__":
    unittest.main()
