"""Isolation guarantees between specialist agents in general-chat.

Every agent profile must get its own runtime (BaseAgent instance, skill
set, MCP tool set), its own curated sources, and — through the per-agent
``/agents/<id>/awp`` surface — its own embed credential and its own pool
of anonymous sessions. Nothing an embed of agent A holds may reach agent
B or any signed-in user's data.
"""

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

from openbench.integrations.firebase_auth import InvalidTokenError  # noqa: E402
from openbench.intelligence.protocol import RouteDecision  # noqa: E402

pytestmark = pytest.mark.integration


def _turn_body(session_id: str) -> dict:
    return {
        "threadId": session_id,
        "messages": [{"id": "m-1", "role": "user", "content": "berapa pajak saya?"}],
    }


class _FakeHandler:
    """Stands in for GeneralChatHandler; records constructor kwargs."""

    captured: dict = {}

    def __init__(self, **kwargs):
        type(self).captured = dict(kwargs)

    async def handle(self, request):
        on_complete = self.captured.get("on_stream_complete")
        if on_complete:
            on_complete(self.captured.get("source_records") or [])
        return JSONResponse({"ok": True})


class _BaseHarness(unittest.TestCase):
    def _env(self, stack: ExitStack, extra: dict[str, str]) -> None:
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
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                    **extra,
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        environ.pop("GENERAL_CHAT_LOCAL_GROUP", None)

    def _patch_agents(self, stack: ExitStack) -> None:
        self.agents_built: list[Mock] = []
        self.build_kwargs: list[dict] = []

        def _fresh_agent(**kwargs):
            agent = Mock()
            agent.model = kwargs.get("model") or "mock-model"
            agent._persona = None
            agent._skill_registry = None
            self.agents_built.append(agent)
            self.build_kwargs.append(kwargs)
            return agent

        stack.enter_context(patch("general_chat.server.app.create_agent", side_effect=_fresh_agent))
        self.mcp_reload = stack.enter_context(
            patch("general_chat.server.app.reload_external_mcp_tools", return_value={})
        )
        self.route_mock = stack.enter_context(
            patch(
                "general_chat.server.app.route",
                return_value=RouteDecision(None, reason="test default"),
            )
        )
        stack.enter_context(patch("general_chat.server.app.GeneralChatHandler", _FakeHandler))
        from general_chat.runtime_settings import (
            set_embedding_options_provider,
            set_model_options_provider,
        )

        self.addCleanup(set_model_options_provider, None)
        self.addCleanup(set_embedding_options_provider, None)

    # ── helpers shared by both harnesses ──────────────────────────────

    @staticmethod
    def _bearer(key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def _post(self, client: TestClient, path: str, session_id: str, headers=None):
        _FakeHandler.captured = {}
        response = client.post(path, json=_turn_body(session_id), headers=headers or {})
        return response, dict(_FakeHandler.captured)


class _LocalHarness(_BaseHarness):
    """Auth disabled: unauthenticated requests are the local admin."""

    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self._env(stack, {"OPENBENCH_AUTH_DISABLED": "1"})
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        self._patch_agents(stack)
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _add_agent(self, client: TestClient, name: str, **extra) -> str:
        response = client.post(
            "/admin/agents", json={"name": name, "description": f"{name}.", **extra}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _enable_embed(self, client: TestClient, agent_id: str) -> str:
        response = client.post(f"/admin/agents/{agent_id}/embed-key")
        self.assertEqual(response.status_code, 200)
        return response.json()["embedKey"]

    def _add_text_source(self, client: TestClient, agent_id: str, name: str) -> None:
        response = client.post(
            f"/admin/agents/{agent_id}/sources/text", json={"name": name, "text": f"Isi {name}."}
        )
        self.assertEqual(response.status_code, 200, response.text)


class _AuthHarness(_BaseHarness):
    """Firebase auth enabled with a verifier that rejects every token, so
    the only credential that can ever pass is an agent embed key. Profiles
    are seeded directly through the store (no admin session available)."""

    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self._env(
            stack,
            {
                "GENERAL_CHAT_FIREBASE_PROJECT_ID": "demo-project",
                "GENERAL_CHAT_ALLOWED_EMAILS": "allowed@example.com",
            },
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)
        self._patch_agents(stack)
        verifier = Mock()
        verifier.verify.side_effect = InvalidTokenError("bad token")
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier
        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    def _seed_agent(self, client: TestClient, agent_id: str, *, embed_key: str = "") -> None:
        from general_chat.agent_store import AgentProfileRecord

        store = client.app.state.agent_profile_store
        store.add(
            AgentProfileRecord(
                id=agent_id,
                name=agent_id.title(),
                description=f"{agent_id}.",
                embed_key=embed_key,
            )
        )


# ── runtime isolation ───────────────────────────────────────────────


class TestRuntimeIsolation(_LocalHarness):
    def test_registry_builds_distinct_agents_per_profile(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        b = self._add_agent(client, "Agen B")
        registry = client.app.state.agent_registry

        agent_a, agent_b = registry.get(a), registry.get(b)
        self.assertIsNot(agent_a, agent_b)
        self.assertIs(registry.get(a), agent_a)  # cached

        registry.invalidate(a)
        self.assertIs(registry.get(b), agent_b)  # b untouched
        self.assertIsNot(registry.get(a), agent_a)  # a rebuilt

    def test_each_profile_is_built_from_its_own_config(self):
        client = self._client()
        options = client.get("/admin/agents/options").json()
        sdk_skills = options["sdkSkills"]
        self.assertGreaterEqual(len(sdk_skills), 2, "need two SDK skills to tell agents apart")
        servers = [server["id"] for server in options["mcpServers"]]

        a = self._add_agent(
            client,
            "Agen A",
            skills=[sdk_skills[0]],
            model=options["models"][0] if options["models"] else "",
            **({"mcpServerIds": servers[:1]} if servers else {}),
        )
        b = self._add_agent(client, "Agen B", skills=[sdk_skills[1]])
        registry = client.app.state.agent_registry

        # Builds so far: the shared default agent. Force the two specialists.
        before = len(self.build_kwargs)
        agent_a = registry.get(a)
        agent_b = registry.get(b)
        built_a, built_b = self.build_kwargs[before], self.build_kwargs[before + 1]
        self.assertEqual(built_a["extra_skill_names"], [sdk_skills[0]])
        self.assertEqual(built_b["extra_skill_names"], [sdk_skills[1]])
        self.assertEqual(built_a["custom_skill_paths"], [])
        self.assertEqual(built_b["custom_skill_paths"], [])
        if servers:
            self.mcp_reload.assert_called_once_with(agent_a, server_ids={servers[0]})
        else:
            self.mcp_reload.assert_not_called()
        # B never received A's MCP tools.
        for call in self.mcp_reload.call_args_list:
            self.assertIsNot(call.args[0], agent_b)


# ── per-agent SSE endpoint ───────────────────────────────────────────


class TestAgentEndpointIsolation(_LocalHarness):
    def test_embed_turn_pins_agent_and_its_sources_only(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        b = self._add_agent(client, "Agen B")
        self._add_text_source(client, a, "Kebijakan A")
        self._add_text_source(client, b, "Kebijakan B")
        key_a = self._enable_embed(client, a)
        registry = client.app.state.agent_registry

        response, captured = self._post(client, f"/agents/{a}/awp", "emb-1", self._bearer(key_a))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(captured["owner"], f"embed:{a}")
        self.assertIs(captured["engine"].agent, registry.get(a))
        self.assertEqual(captured["agent_descriptor"].id, a)
        owners = {record.owner for record in captured["source_records"]}
        self.assertIn(f"agent:{a}", owners)
        self.assertNotIn(f"agent:{b}", owners)
        self.route_mock.assert_not_called()

    def test_pinned_session_rejected_on_other_agent_for_same_owner(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        b = self._add_agent(client, "Agen B")
        registry = client.app.state.agent_registry

        ok, captured = self._post(client, f"/agents/{a}/awp", "s1")
        self.assertEqual(ok.status_code, 200)
        self.assertIs(captured["engine"].agent, registry.get(a))

        conflict, _ = self._post(client, f"/agents/{b}/awp", "s1")
        self.assertEqual(conflict.status_code, 409)

        # The pin is persisted: the generic endpoint now serves agent A
        # for this session without consulting the router.
        generic, captured = self._post(client, "/awp", "s1")
        self.assertEqual(generic.status_code, 200)
        self.assertIs(captured["engine"].agent, registry.get(a))
        self.route_mock.assert_not_called()
        selection = client.get("/chat/agent-selection", params={"threadId": "s1"}).json()
        self.assertEqual(selection["agentId"], a)

    def test_embed_sessions_live_under_the_embed_owner(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        b = self._add_agent(client, "Agen B")
        key_a = self._enable_embed(client, a)
        key_b = self._enable_embed(client, b)

        ok, _ = self._post(client, f"/agents/{a}/awp", "shared-id", self._bearer(key_a))
        self.assertEqual(ok.status_code, 200)
        # Same thread id through agent B's key: different owner -> not found.
        other, _ = self._post(client, f"/agents/{b}/awp", "shared-id", self._bearer(key_b))
        self.assertEqual(other.status_code, 404)
        # The local admin's session list never shows embed sessions.
        listed = client.get("/sessions").json()
        self.assertNotIn("shared-id", str(listed))
        # Embeds keep no history at all, and unknown per-agent paths are a
        # JSON 404 (never the SPA's index.html).
        self.assertEqual(
            client.get(f"/agents/{a}/sessions", headers=self._bearer(key_a)).status_code, 501
        )
        probe = client.get(f"/agents/{a}/sessions/shared-id", headers=self._bearer(key_a))
        self.assertEqual(probe.status_code, 404)
        self.assertEqual(probe.json(), {"detail": "Not found"})

    def test_disabled_or_missing_agent_is_unreachable(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        key_a = self._enable_embed(client, a)
        self.assertEqual(client.put(f"/admin/agents/{a}", json={"enabled": False}).status_code, 200)

        as_admin, _ = self._post(client, f"/agents/{a}/awp", "s1")
        self.assertEqual(as_admin.status_code, 404)
        self.assertEqual(client.get(f"/agents/{a}", headers=self._bearer(key_a)).status_code, 404)
        ghost, _ = self._post(client, "/agents/ghost/awp", "s1")
        self.assertEqual(ghost.status_code, 404)

    def test_public_card_never_leaks_the_key(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        key_a = self._enable_embed(client, a)
        card = client.get(f"/agents/{a}", headers=self._bearer(key_a))
        self.assertEqual(card.status_code, 200)
        self.assertEqual(set(card.json()), {"id", "name", "description"})

    def test_generic_awp_unchanged_with_zero_profiles(self):
        client = self._client()
        response, captured = self._post(client, "/awp", "s1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("agent_descriptor", captured)
        self.assertIs(captured["engine"].agent, self.agents_built[0])
        self.route_mock.assert_not_called()

    def test_audit_marks_embed_turns(self):
        client = self._client()
        a = self._add_agent(client, "Agen A")
        key_a = self._enable_embed(client, a)
        self._post(client, f"/agents/{a}/awp", "emb-1", self._bearer(key_a))
        items = client.get("/admin/audit?limit=50").json()["items"]
        turns = [item for item in items if item["action"] == "chat.turn"]
        self.assertTrue(turns)
        self.assertEqual(turns[0]["actor"], f"embed:{a}")
        self.assertEqual(turns[0]["role"], "user")
        self.assertIs(turns[0]["detail"]["embed"], True)
        self.assertEqual(turns[0]["detail"]["agent"], a)


# ── credential scope (auth enabled) ──────────────────────────────────


class TestEmbedKeyScope(_AuthHarness):
    def test_key_of_one_agent_never_opens_another(self):
        client = self._client()
        self._seed_agent(client, "agen-a", embed_key="key-a-" + "x" * 32)
        self._seed_agent(client, "agen-b", embed_key="key-b-" + "y" * 32)

        own, _ = self._post(client, "/agents/agen-a/awp", "s1", self._bearer("key-a-" + "x" * 32))
        self.assertEqual(own.status_code, 200, own.text)
        cross, _ = self._post(client, "/agents/agen-a/awp", "s1", self._bearer("key-b-" + "y" * 32))
        self.assertEqual(cross.status_code, 401)
        missing, _ = self._post(client, "/agents/agen-a/awp", "s1")
        self.assertEqual(missing.status_code, 401)
        wrong, _ = self._post(client, "/agents/agen-a/awp", "s1", self._bearer("nope"))
        self.assertEqual(wrong.status_code, 401)

    def test_key_never_authorizes_other_prefixes(self):
        client = self._client()
        key = "key-a-" + "x" * 32
        self._seed_agent(client, "agen-a", embed_key=key)
        headers = self._bearer(key)
        for method, path in (
            ("GET", "/sessions"),
            ("GET", "/admin/agents"),
            ("GET", "/chat/agents"),
            ("GET", "/account/me"),
            ("POST", "/awp"),
        ):
            response = client.request(method, path, json=_turn_body("s1"), headers=headers)
            self.assertEqual(response.status_code, 401, f"{method} {path}: {response.status_code}")

    def test_revoked_or_disabled_key_stops_working(self):
        client = self._client()
        key = "key-a-" + "x" * 32
        self._seed_agent(client, "agen-a", embed_key=key)
        store = client.app.state.agent_profile_store

        ok, _ = self._post(client, "/agents/agen-a/awp", "s1", self._bearer(key))
        self.assertEqual(ok.status_code, 200)

        store.update("agen-a", {"enabled": False})
        disabled, _ = self._post(client, "/agents/agen-a/awp", "s1", self._bearer(key))
        self.assertEqual(disabled.status_code, 401)

        store.update("agen-a", {"enabled": True, "embed_key": ""})
        revoked, _ = self._post(client, "/agents/agen-a/awp", "s1", self._bearer(key))
        self.assertEqual(revoked.status_code, 401)
