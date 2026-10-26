"""Tests for per-session agent selection and auto-routing on /awp."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from openbench.intelligence.protocol import RouteDecision  # noqa: E402

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

        self.agents_built: list[Mock] = []

        def _fresh_agent(**kwargs):
            agent = Mock()
            agent.model = kwargs.get("model") or "mock-model"
            agent._persona = None
            agent._skill_registry = None
            self.agents_built.append(agent)
            return agent

        stack.enter_context(patch("general_chat.server.app.create_agent", side_effect=_fresh_agent))
        self.route_mock = stack.enter_context(
            patch(
                "general_chat.server.app.route",
                return_value=RouteDecision(None, reason="test default"),
            )
        )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _add_agent(self, client: TestClient, name: str = "Analis Keuangan") -> str:
        response = client.post("/admin/agents", json={"name": name, "description": "Keuangan."})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def _post_awp(self, client: TestClient, session_id: str = "sess-1") -> dict:
        """POST /awp with a fake handler; returns the captured handler kwargs."""
        captured: dict = {}

        class _FakeHandler:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def handle(self, request):
                on_complete = captured.get("on_stream_complete")
                if on_complete:
                    on_complete(captured.get("source_records") or [])
                return JSONResponse({"ok": True})

        with patch("general_chat.server.app.GeneralChatHandler", _FakeHandler):
            response = client.post(
                "/awp",
                json={
                    "threadId": session_id,
                    "messages": [{"role": "user", "content": "berapa pajak saya?"}],
                },
            )
        self.assertEqual(response.status_code, 200)
        return captured


class TestSelectionEndpoints(_AppHarness):
    def test_list_chat_agents(self):
        client = self._client()
        self.assertEqual(
            client.get("/chat/agents").json(), {"agents": [], "defaultMode": "default"}
        )
        self._add_agent(client)
        payload = client.get("/chat/agents").json()
        self.assertEqual(payload["defaultMode"], "auto")
        self.assertEqual(
            payload["agents"],
            [
                {
                    "id": "analis-keuangan",
                    "name": "Analis Keuangan",
                    "description": "Keuangan.",
                }
            ],
        )

    def test_selection_round_trip(self):
        client = self._client()
        self._add_agent(client)
        # Unset selection defaults to auto once profiles exist.
        empty = client.get("/chat/agent-selection", params={"threadId": "sess-1"}).json()
        self.assertEqual(empty["agentId"], "auto")

        saved = client.put(
            "/chat/agent-selection",
            json={"threadId": "sess-1", "agentId": "analis-keuangan"},
        )
        self.assertEqual(saved.status_code, 200)
        fetched = client.get("/chat/agent-selection", params={"threadId": "sess-1"}).json()
        self.assertEqual(fetched["agentId"], "analis-keuangan")

        # Explicit default-assistant choice persists as "" — distinct from
        # an unset session (which reads back as "auto").
        client.put("/chat/agent-selection", json={"threadId": "sess-1", "agentId": ""})
        self.assertEqual(
            client.get("/chat/agent-selection", params={"threadId": "sess-1"}).json()["agentId"],
            "",
        )

    def test_selection_validation(self):
        client = self._client()
        self.assertEqual(
            client.put(
                "/chat/agent-selection", json={"threadId": "s", "agentId": "ghost"}
            ).status_code,
            400,
        )
        self.assertEqual(
            client.put("/chat/agent-selection", json={"agentId": "auto"}).status_code,
            400,
        )

    def test_stale_selection_returns_default(self):
        client = self._client()
        agent_id = self._add_agent(client)
        client.put("/chat/agent-selection", json={"threadId": "s1", "agentId": agent_id})
        client.delete(f"/admin/agents/{agent_id}")
        # Profile gone: stored id no longer valid, no profiles left => "".
        self.assertEqual(
            client.get("/chat/agent-selection", params={"threadId": "s1"}).json()["agentId"],
            "",
        )

    def test_capability_gate(self):
        client = self._client()
        client.put("/admin/capabilities", json={"roles": {"user": {"agent_selection": False}}})
        headers = {"X-Local-Role": "user"}
        self.assertEqual(client.get("/chat/agents", headers=headers).status_code, 403)
        self.assertEqual(
            client.get(
                "/chat/agent-selection", params={"threadId": "s"}, headers=headers
            ).status_code,
            403,
        )
        # Admins bypass.
        self.assertEqual(client.get("/chat/agents").status_code, 200)


class TestAwpRouting(_AppHarness):
    def test_zero_profiles_uses_default_agent_and_skips_router(self):
        client = self._client()
        default_agent = client.app.state.agent_registry and self.agents_built[0]
        captured = self._post_awp(client)
        self.assertIs(captured["engine"].agent, default_agent)
        self.route_mock.assert_not_called()

    def test_auto_routes_to_specialist(self):
        client = self._client()
        agent_id = self._add_agent(client)
        self.route_mock.return_value = RouteDecision(agent_id, reason="match")
        captured = self._post_awp(client)
        self.route_mock.assert_called_once()
        specialist = client.app.state.agent_registry.get(agent_id)
        self.assertIs(captured["engine"].agent, specialist)
        # The router saw the latest user message.
        args = self.route_mock.call_args.args
        self.assertEqual(args[0], "berapa pajak saya?")

    def test_auto_router_none_falls_back_to_default(self):
        client = self._client()
        self._add_agent(client)
        self.route_mock.return_value = RouteDecision(None, reason="no fit")
        captured = self._post_awp(client)
        self.assertIs(captured["engine"].agent, self.agents_built[0])

    def test_explicit_selection_skips_router(self):
        client = self._client()
        agent_id = self._add_agent(client)
        client.put("/chat/agent-selection", json={"threadId": "sess-1", "agentId": agent_id})
        captured = self._post_awp(client)
        self.route_mock.assert_not_called()
        specialist = client.app.state.agent_registry.get(agent_id)
        self.assertIs(captured["engine"].agent, specialist)

    def test_explicit_default_selection_skips_router(self):
        client = self._client()
        self._add_agent(client)
        client.put("/chat/agent-selection", json={"threadId": "sess-1", "agentId": ""})
        captured = self._post_awp(client)
        self.route_mock.assert_not_called()
        self.assertIs(captured["engine"].agent, self.agents_built[0])

    def test_router_crash_falls_back_to_default(self):
        client = self._client()
        self._add_agent(client)
        self.route_mock.side_effect = RuntimeError("router down")
        captured = self._post_awp(client)
        self.assertIs(captured["engine"].agent, self.agents_built[0])

    def test_agent_sources_ground_the_turn_and_survive_cleanup(self):
        client = self._client()
        agent_id = self._add_agent(client)
        client.post(
            f"/admin/agents/{agent_id}/sources/text",
            json={"name": "Kebijakan Agen", "text": "Batas reimburse Rp2.000.000."},
        )
        client.put("/chat/agent-selection", json={"threadId": "sess-1", "agentId": agent_id})
        captured = self._post_awp(client)
        records = captured["source_records"]
        self.assertEqual([r.name for r in records], ["Kebijakan Agen"])
        self.assertTrue(all(r.owner == f"agent:{agent_id}" for r in records))
        # The turn-end cleanup ran over the records; the agent source must
        # survive it (cleanup only ever touches the session slice).
        still_there = client.get(f"/admin/agents/{agent_id}/sources").json()["sources"]
        self.assertEqual(len(still_there), 1)

    def test_use_sources_false_skips_agent_records(self):
        client = self._client()
        agent_id = self._add_agent(client)
        client.post(
            f"/admin/agents/{agent_id}/sources/text",
            json={"name": "Kebijakan Agen", "text": "Isi."},
        )
        client.put(f"/admin/agents/{agent_id}", json={"useSources": False})
        client.put("/chat/agent-selection", json={"threadId": "sess-1", "agentId": agent_id})
        captured = self._post_awp(client)
        self.assertEqual(captured["source_records"], [])


if __name__ == "__main__":
    unittest.main()
