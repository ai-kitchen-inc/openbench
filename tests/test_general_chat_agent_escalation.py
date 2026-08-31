"""Tests for escalation wiring in the chat handler and engine pipeline."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pytest

_EXAMPLE_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(_EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_SRC))

from general_chat.server.handler import GeneralChatHandler  # noqa: E402

from openbench.chat import ChatEngine  # noqa: E402
from openbench.core.abstractions import ExecutionResult  # noqa: E402
from openbench.intelligence.base import BaseAgent  # noqa: E402
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore  # noqa: E402
from openbench.intelligence.protocol import AgentDescriptor, ProtocolAgent  # noqa: E402

pytestmark = pytest.mark.integration

PRIMARY = AgentDescriptor(id="analis", name="Analis Keuangan", description="Keuangan.")
FALLBACK = AgentDescriptor(id="senior", name="Konsultan Senior", description="Senior.")


def _base_agent(goal: str = "Bantu pengguna.") -> BaseAgent:
    return BaseAgent(goal=goal, model="gemini-2.5-flash")


class _FakeEngine:
    def __init__(self, agent):
        self.agent = agent


class _HandlerHarness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = SQLiteMemoryStore(db_path=str(Path(tmp.name) / "memory.db"))

    def _handler(self, agent, **kwargs) -> GeneralChatHandler:
        return GeneralChatHandler(
            engine=_FakeEngine(agent),
            memory_store=self.store,
            **kwargs,
        )


class TestRequestAgentWiring(_HandlerHarness):
    def test_default_path_returns_bare_base_agent(self):
        """No profile => no wrapper — the controlled-source-chat guarantee."""
        agent = _base_agent()
        handler = self._handler(agent)
        handler._local.session_id = "sess-1"
        request_agent = handler._create_request_agent()
        self.assertIsInstance(request_agent, BaseAgent)
        self.assertNotIsInstance(request_agent, ProtocolAgent)
        self.assertIsNot(request_agent, agent)  # per-turn copy
        self.assertIsInstance(request_agent.memory, PersistentMemory)

    def test_descriptor_wraps_in_protocol_agent(self):
        agent = _base_agent()
        handler = self._handler(agent, agent_descriptor=PRIMARY, confidence_threshold=0.7)
        handler._local.session_id = "sess-1"
        request_agent = handler._create_request_agent()
        self.assertIsInstance(request_agent, ProtocolAgent)
        self.assertIs(request_agent.descriptor, PRIMARY)
        self.assertIsNone(request_agent.fallback)
        self.assertEqual(request_agent.confidence_threshold, 0.7)
        # The wrapped primary is a prepared per-turn copy, not the shared agent.
        self.assertIsNot(request_agent.inner, agent)
        self.assertIsInstance(request_agent.inner.memory, PersistentMemory)

    def test_escalation_agent_is_prepared_too(self):
        agent = _base_agent()
        escalation_source = _base_agent("Jawab sebagai konsultan senior.")
        handler = self._handler(
            agent,
            agent_descriptor=PRIMARY,
            escalation_agent=escalation_source,
            escalation_descriptor=FALLBACK,
        )
        handler._local.session_id = "sess-1"
        request_agent = handler._create_request_agent()
        self.assertIsInstance(request_agent, ProtocolAgent)
        self.assertIsNotNone(request_agent.fallback)
        self.assertIsNot(request_agent.fallback, escalation_source)
        self.assertIsInstance(request_agent.fallback.memory, PersistentMemory)
        self.assertIs(request_agent.fallback_descriptor, FALLBACK)

    def test_engine_agent_stays_raw(self):
        """Title generation and vision helpers read engine.agent directly."""
        agent = _base_agent()
        handler = self._handler(agent, agent_descriptor=PRIMARY)
        handler._local.session_id = "sess-1"
        handler._create_request_agent()
        self.assertIs(handler.engine.agent, agent)


class _ScriptedAgent:
    """Engine-compatible stand-in whose execute returns a scripted answer."""

    def __init__(self, output: str):
        self.output = output
        self.memory = None

    def execute(self, context, on_chunk=None, on_progress=None):
        if on_chunk:
            on_chunk(self.output)
        return ExecutionResult(output=self.output, status="completed", metadata={})


class TestEnginePipelineMetadata(unittest.TestCase):
    """ProtocolAgent results flow through ChatEngine into session metadata."""

    def test_marker_stripped_and_identity_metadata_persisted(self):
        agent = ProtocolAgent(_ScriptedAgent("Jawaban rapi.\n\n[[CONFIDENCE=0.9]]"), PRIMARY)
        engine = ChatEngine(agent=agent)
        engine.invoke({"content": "berapa pajak saya?"})
        assistant = engine.session.messages[-1]
        self.assertNotIn("[[CONFIDENCE", assistant.content)
        self.assertIn("Jawaban rapi.", assistant.content)
        self.assertEqual(assistant.metadata.get("agentId"), "analis")
        self.assertEqual(assistant.metadata.get("agentName"), "Analis Keuangan")

    def test_escalated_turn_metadata(self):
        agent = ProtocolAgent(
            _ScriptedAgent("ragu\n[[CONFIDENCE=0.1]]"),
            PRIMARY,
            fallback=_ScriptedAgent("Jawaban senior."),
            fallback_descriptor=FALLBACK,
        )
        engine = ChatEngine(agent=agent)
        engine.invoke({"content": "pertanyaan sulit"})
        assistant = engine.session.messages[-1]
        self.assertIn("Jawaban senior.", assistant.content)
        self.assertNotIn("ragu", assistant.content)
        self.assertTrue(assistant.metadata.get("escalated"))
        self.assertEqual(assistant.metadata.get("escalatedFrom"), "analis")
        self.assertEqual(assistant.metadata.get("agentName"), "Konsultan Senior")


if __name__ == "__main__":
    unittest.main()
