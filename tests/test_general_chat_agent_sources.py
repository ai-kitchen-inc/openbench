"""Tests for agent-scoped curated sources (/admin/agents/{id}/sources)."""

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
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _add_agent(self, client: TestClient, name: str = "Analis Keuangan") -> str:
        response = client.post("/admin/agents", json={"name": name, "description": "Keuangan."})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]


class TestAgentSources(_AppHarness):
    def test_text_source_add_list_delete(self):
        client = self._client()
        agent_id = self._add_agent(client)
        created = client.post(
            f"/admin/agents/{agent_id}/sources/text",
            json={"name": "Kebijakan", "text": "Batas reimburse Rp2.000.000."},
        )
        self.assertEqual(created.status_code, 200)
        source_id = created.json()["id"]

        listed = client.get(f"/admin/agents/{agent_id}/sources").json()["sources"]
        self.assertEqual([source["name"] for source in listed], ["Kebijakan"])

        deleted = client.delete(f"/admin/agents/{agent_id}/sources/{source_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get(f"/admin/agents/{agent_id}/sources").json()["sources"], [])

    def test_unknown_agent_404(self):
        client = self._client()
        self.assertEqual(client.get("/admin/agents/ghost/sources").status_code, 404)
        self.assertEqual(
            client.post(
                "/admin/agents/ghost/sources/text", json={"name": "x", "text": "y"}
            ).status_code,
            404,
        )

    def test_delete_missing_source_404(self):
        client = self._client()
        agent_id = self._add_agent(client)
        self.assertEqual(client.delete(f"/admin/agents/{agent_id}/sources/nope").status_code, 404)

    def test_admin_only(self):
        client = self._client()
        agent_id = self._add_agent(client)
        headers = {"X-Local-Role": "user"}
        self.assertEqual(
            client.get(f"/admin/agents/{agent_id}/sources", headers=headers).status_code,
            403,
        )

    def test_profile_delete_purges_sources(self):
        client = self._client()
        agent_id = self._add_agent(client)
        client.post(
            f"/admin/agents/{agent_id}/sources/text",
            json={"name": "Kebijakan", "text": "Isi kebijakan."},
        )
        client.delete(f"/admin/agents/{agent_id}")
        # Recreating the same profile starts with a clean source slate.
        recreated = self._add_agent(client)
        self.assertEqual(recreated, agent_id)
        self.assertEqual(client.get(f"/admin/agents/{agent_id}/sources").json()["sources"], [])

    def test_sources_scoped_per_agent(self):
        client = self._client()
        first = self._add_agent(client, "Analis Keuangan")
        second = self._add_agent(client, "Peninjau Legal")
        client.post(
            f"/admin/agents/{first}/sources/text",
            json={"name": "Kebijakan Keuangan", "text": "Isi."},
        )
        self.assertEqual(
            [s["name"] for s in client.get(f"/admin/agents/{first}/sources").json()["sources"]],
            ["Kebijakan Keuangan"],
        )
        self.assertEqual(client.get(f"/admin/agents/{second}/sources").json()["sources"], [])


if __name__ == "__main__":
    unittest.main()
