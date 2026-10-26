"""Tests for the per-profile agent registry and profile agent factory."""

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

from general_chat.agent_store import AgentProfileRecord, JsonAgentProfileStore  # noqa: E402
from general_chat.server.agent_registry import (  # noqa: E402
    AgentProfileRegistry,
    descriptor_from_profile,
)

pytestmark = pytest.mark.integration


def _record(agent_id: str = "analis-keuangan", **overrides) -> AgentProfileRecord:
    values = {
        "id": agent_id,
        "name": "Analis Keuangan",
        "description": "Laporan keuangan, anggaran, pajak.",
    }
    values.update(overrides)
    return AgentProfileRecord(**values)


class TestDescriptorFromProfile(unittest.TestCase):
    def test_maps_identity_fields(self):
        descriptor = descriptor_from_profile(_record(model="gemini-2.5-pro"))
        self.assertEqual(descriptor.id, "analis-keuangan")
        self.assertEqual(descriptor.name, "Analis Keuangan")
        self.assertEqual(descriptor.description, "Laporan keuangan, anggaran, pajak.")
        self.assertEqual(descriptor.model, "gemini-2.5-pro")


class TestAgentProfileRegistry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonAgentProfileStore(tmp.name)
        self.built: list[str] = []

        def build(profile: AgentProfileRecord):
            self.built.append(profile.id)
            return Mock(name=f"agent-{profile.id}")

        self.registry = AgentProfileRegistry(self.store, build)

    def test_lazy_build_and_cache(self):
        self.store.add(_record())
        self.assertEqual(self.built, [])  # nothing built until first get
        first = self.registry.get("analis-keuangan")
        second = self.registry.get("analis-keuangan")
        self.assertIs(first, second)
        self.assertEqual(self.built, ["analis-keuangan"])

    def test_unknown_and_disabled_return_none(self):
        self.store.add(_record(enabled=False))
        self.assertIsNone(self.registry.get("missing"))
        self.assertIsNone(self.registry.get("analis-keuangan"))
        self.assertIsNone(self.registry.get(""))
        self.assertEqual(self.built, [])

    def test_invalidate_rebuilds(self):
        self.store.add(_record())
        first = self.registry.get("analis-keuangan")
        self.registry.invalidate("analis-keuangan")
        second = self.registry.get("analis-keuangan")
        self.assertIsNot(first, second)
        self.assertEqual(self.built, ["analis-keuangan", "analis-keuangan"])

    def test_invalidate_all(self):
        self.store.add(_record())
        self.store.add(_record("legal", name="Peninjau Legal"))
        self.registry.get("analis-keuangan")
        self.registry.get("legal")
        self.registry.invalidate()
        self.registry.get("analis-keuangan")
        self.assertEqual(self.built.count("analis-keuangan"), 2)

    def test_descriptors_skip_disabled_and_never_build(self):
        self.store.add(_record())
        self.store.add(_record("nonaktif", name="Nonaktif", enabled=False))
        descriptors = self.registry.descriptors()
        self.assertEqual([d.id for d in descriptors], ["analis-keuangan"])
        self.assertEqual(self.built, [])

    def test_directory_resolves_through_registry(self):
        self.store.add(_record())
        directory = self.registry.directory()
        self.assertEqual([d.id for d in directory.descriptors()], ["analis-keuangan"])
        agent = directory.resolve("analis-keuangan")
        self.assertIs(agent, self.registry.get("analis-keuangan"))

    def test_failed_build_leaves_no_cache(self):
        self.store.add(_record())

        def broken(profile):
            raise RuntimeError("boom")

        registry = AgentProfileRegistry(self.store, broken)
        with self.assertRaises(RuntimeError):
            registry.get("analis-keuangan")
        # A later fixed build succeeds (no poisoned cache entry).
        registry._build_agent = lambda profile: Mock()
        self.assertIsNotNone(registry.get("analis-keuangan"))


class TestProfileFactoryInApp(unittest.TestCase):
    """The app-level factory must route through the patched create_agent."""

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
        self.create_agent = stack.enter_context(
            patch("general_chat.server.app.create_agent", return_value=agent)
        )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_registry_builds_profiles_via_create_agent(self):
        client = self._client()
        registry = client.app.state.agent_registry
        store = client.app.state.agent_profile_store
        store.add(
            _record(
                model="gemini-2.5-pro",
                temperature=0.1,
                skills=["query-explorer"],
            )
        )
        calls_before = self.create_agent.call_count
        agent = registry.get("analis-keuangan")
        self.assertIsNotNone(agent)
        self.assertEqual(self.create_agent.call_count, calls_before + 1)
        kwargs = self.create_agent.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-2.5-pro")
        self.assertEqual(kwargs["temperature"], 0.1)
        self.assertEqual(kwargs["extra_skill_names"], ["query-explorer"])

    def test_escalation_profile_gets_confidence_protocol(self):
        client = self._client()
        registry = client.app.state.agent_registry
        store = client.app.state.agent_profile_store
        store.add(
            _record(
                persona={"soul": "Saya analis.", "agents": "Selalu teliti."},
                escalation_agent_id="konsultan-senior",
            )
        )
        registry.get("analis-keuangan")
        kwargs = self.create_agent.call_args.kwargs
        persona = kwargs["persona"]
        self.assertIsNotNone(persona)
        composed = persona.compose()
        self.assertIn("Selalu teliti.", composed)
        self.assertIn("[[CONFIDENCE=0.8]]", composed)

    def test_zero_profiles_registry_is_empty(self):
        client = self._client()
        registry = client.app.state.agent_registry
        self.assertEqual(registry.descriptors(), [])
        self.assertEqual(len(registry.directory()), 0)


class TestCreateAgentExtraSkills(unittest.TestCase):
    def test_unknown_extra_skill_raises(self):
        from general_chat.agent import _sdk_skill_dir, create_agent

        self.assertFalse(_sdk_skill_dir("does-not-exist").is_dir())
        with (
            patch.dict(environ, {"GOOGLE_API_KEY": "test-key"}, clear=False),
            self.assertRaises(ValueError),
        ):
            create_agent(extra_skill_names=["does-not-exist"])


if __name__ == "__main__":
    unittest.main()
