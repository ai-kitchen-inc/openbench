"""Hermes-backed agent profiles in general-chat.

A profile with ``runtime == "hermes"`` must be answered by its own Hermes
profile (own URL + own env-held key) and must never share a Hermes
endpoint or credential with another agent. Default-runtime profiles stay
bit-identical to the pre-Hermes behavior.
"""

from __future__ import annotations

import sys
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

import pytest

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.agent_store import RUNTIME_HERMES, AgentProfileRecord  # noqa: E402
from general_chat.hermes_runtime import (  # noqa: E402
    HermesRuntimeConfigError,
    build_hermes_agent,
    hermes_key_env_name,
    validate_hermes_url,
)

from openbench.adapters.hermes import HermesAgent  # noqa: E402
from tests.test_general_chat_agent_isolation import _LocalHarness  # noqa: E402


class TestAgentProfileRuntimeFields(unittest.TestCase):
    def test_defaults_to_openbench_runtime(self):
        record = AgentProfileRecord.from_dict({"id": "a", "name": "A"})
        self.assertEqual(record.runtime, "")
        self.assertEqual(record.hermes_url, "")

    def test_round_trip(self):
        record = AgentProfileRecord(id="a", name="A")
        record.apply_changes({"runtime": "HERMES", "hermes_url": " http://h:8643 "})
        restored = AgentProfileRecord.from_dict(record.to_dict())
        self.assertEqual(restored.runtime, RUNTIME_HERMES)
        self.assertEqual(restored.hermes_url, "http://h:8643")

    def test_unknown_runtime_falls_back_to_default(self):
        record = AgentProfileRecord.from_dict({"id": "a", "name": "A", "runtime": "skynet"})
        self.assertEqual(record.runtime, "")


class TestHermesRuntimeHelpers(unittest.TestCase):
    def test_key_env_name(self):
        self.assertEqual(
            hermes_key_env_name("agen-pajak-2"), "GENERAL_CHAT_HERMES_KEY_AGEN_PAJAK_2"
        )

    def test_validate_url(self):
        self.assertEqual(validate_hermes_url(" http://10.0.0.5:8643/ "), "http://10.0.0.5:8643")
        for bad in ("", "ftp://h", "h:8643", "http://u:p@h", "http://h?x=1", "http://h#f"):
            with self.assertRaises(ValueError, msg=bad):
                validate_hermes_url(bad)

    def test_build_reads_only_this_agents_key(self):
        a = AgentProfileRecord(id="agen-a", name="A", runtime="hermes", hermes_url="http://h:8643")
        b = AgentProfileRecord(id="agen-b", name="B", runtime="hermes", hermes_url="http://h:8644")
        env = {hermes_key_env_name("agen-a"): "key-a", hermes_key_env_name("agen-b"): "key-b"}
        with patch.dict(environ, env, clear=False):
            agent_a, agent_b = build_hermes_agent(a), build_hermes_agent(b)
        self.assertIsInstance(agent_a, HermesAgent)
        self.assertEqual(agent_a.adapter.base_url, "http://h:8643")
        self.assertEqual(agent_b.adapter.base_url, "http://h:8644")
        self.assertEqual(agent_a.adapter._api_key, "key-a")
        self.assertEqual(agent_b.adapter._api_key, "key-b")
        self.assertEqual(agent_a.model, "agen-a")

    def test_build_fails_without_key_or_url(self):
        record = AgentProfileRecord(id="agen-a", name="A", runtime="hermes", hermes_url="http://h")
        environ.pop(hermes_key_env_name("agen-a"), None)
        with self.assertRaises(HermesRuntimeConfigError):
            build_hermes_agent(record)
        record.hermes_url = ""
        with (
            patch.dict(environ, {hermes_key_env_name("agen-a"): "k"}, clear=False),
            self.assertRaises(HermesRuntimeConfigError),
        ):
            build_hermes_agent(record)


@pytest.mark.integration
class TestHermesProfilesInApp(_LocalHarness):
    def test_hermes_profile_builds_hermes_agent_not_base_agent(self):
        client = self._client()
        hermes_id = self._add_agent(
            client, "Agen Hermes", runtime="hermes", hermesUrl="http://127.0.0.1:8643/"
        )
        plain_id = self._add_agent(client, "Agen Biasa")
        registry = client.app.state.agent_registry
        before = len(self.build_kwargs)

        with patch.dict(environ, {hermes_key_env_name(hermes_id): "key-h"}, clear=False):
            hermes_agent = registry.get(hermes_id)
        plain_agent = registry.get(plain_id)

        self.assertIsInstance(hermes_agent, HermesAgent)
        self.assertEqual(hermes_agent.adapter.base_url, "http://127.0.0.1:8643")
        # Only the default-runtime profile went through create_agent.
        self.assertEqual(len(self.build_kwargs), before + 1)
        self.assertIs(plain_agent, self.agents_built[-1])
        self.mcp_reload.assert_not_called()

    def test_profile_payload_never_carries_a_hermes_key(self):
        client = self._client()
        agent_id = self._add_agent(client, "Agen Hermes", runtime="hermes", hermesUrl="http://h:1")
        with patch.dict(environ, {hermes_key_env_name(agent_id): "super-secret"}, clear=False):
            payload = client.get(f"/admin/agents/{agent_id}").text
        self.assertNotIn("super-secret", payload)
        self.assertEqual(client.get(f"/admin/agents/{agent_id}").json()["runtime"], "hermes")

    def test_validation(self):
        client = self._client()
        bad_runtime = client.post(
            "/admin/agents", json={"name": "X", "description": "x.", "runtime": "skynet"}
        )
        self.assertEqual(bad_runtime.status_code, 400)
        missing_url = client.post(
            "/admin/agents", json={"name": "Y", "description": "y.", "runtime": "hermes"}
        )
        self.assertEqual(missing_url.status_code, 400)
        bad_url = client.post(
            "/admin/agents",
            json={"name": "Z", "description": "z.", "runtime": "hermes", "hermesUrl": "ftp://h"},
        )
        self.assertEqual(bad_url.status_code, 400)

    def test_switching_back_to_default_runtime_rebuilds_as_base_agent(self):
        client = self._client()
        agent_id = self._add_agent(client, "Agen Hermes", runtime="hermes", hermesUrl="http://h:1")
        registry = client.app.state.agent_registry
        with patch.dict(environ, {hermes_key_env_name(agent_id): "k"}, clear=False):
            self.assertIsInstance(registry.get(agent_id), HermesAgent)

        response = client.put(f"/admin/agents/{agent_id}", json={"runtime": ""})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIsInstance(registry.get(agent_id), HermesAgent)

    def test_forced_turn_on_unbuildable_hermes_agent_is_503_not_fallback(self):
        client = self._client()
        agent_id = self._add_agent(client, "Agen Hermes", runtime="hermes", hermesUrl="http://h:1")
        key = self._enable_embed(client, agent_id)
        environ.pop(hermes_key_env_name(agent_id), None)
        response, captured = self._post(
            client, f"/agents/{agent_id}/awp", "s-1", headers=self._bearer(key)
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(captured, {})


if __name__ == "__main__":
    unittest.main()
