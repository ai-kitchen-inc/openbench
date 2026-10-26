"""Tests for the ProtocolAgent escalation wrapper."""

import pytest

from openbench.core.abstractions import ExecutionContext, ExecutionResult
from openbench.intelligence.protocol import AgentDescriptor
from openbench.intelligence.protocol.agent import ProtocolAgent


class _StubMemory:
    def __init__(self):
        self.messages = ["system"]
        self.truncated_to = None

    def truncate_to(self, length: int) -> None:
        self.truncated_to = length
        self.messages = self.messages[:length]


class _StubAgent:
    """Minimal agent: scripted output, records how it was called."""

    def __init__(self, output: str, with_memory: bool = True):
        self.output = output
        self.memory = _StubMemory() if with_memory else None
        self.calls = []

    def execute(self, context, on_chunk=None, on_progress=None):
        self.calls.append({"on_chunk": on_chunk, "on_progress": on_progress})
        if self.memory is not None:
            self.memory.messages += ["user", "assistant"]
        if on_chunk:
            on_chunk(self.output)
        return ExecutionResult(output=self.output, status="completed", metadata={})

    def estimate_cost(self, context):
        return 0.01


class _LegacyAgent:
    """Agent whose execute() takes no streaming kwargs."""

    def execute(self, context):
        return ExecutionResult(output="legacy", status="completed", metadata={})


PRIMARY = AgentDescriptor(id="finance-analyst", name="Analis Keuangan", description="Keuangan.")
FALLBACK = AgentDescriptor(id="senior-consultant", name="Konsultan Senior", description="Senior.")
CONTEXT = ExecutionContext(goal="berapa pajak saya?", data={})


class TestPassthrough:
    def test_streams_live_and_adds_identity_metadata(self):
        inner = _StubAgent("jawaban")
        chunks, events = [], []
        agent = ProtocolAgent(inner, PRIMARY)
        result = agent.execute(CONTEXT, on_chunk=chunks.append, on_progress=events.append)
        assert result.output == "jawaban"
        assert chunks == ["jawaban"]  # inner streamed directly
        assert inner.calls[0]["on_chunk"] is not None
        assert result.metadata["agentId"] == "finance-analyst"
        assert result.metadata["agentName"] == "Analis Keuangan"
        assert "escalated" not in result.metadata
        assert events[0].phase == "Agen: Analis Keuangan"

    def test_stray_marker_stripped_even_without_fallback(self):
        inner = _StubAgent("jawaban\n[[CONFIDENCE=0.9]]")
        agent = ProtocolAgent(inner, PRIMARY)
        result = agent.execute(CONTEXT)
        assert result.output == "jawaban"
        assert result.metadata["confidence"] == 0.9

    def test_agent_type_and_cost_delegation(self):
        agent = ProtocolAgent(_StubAgent("x"), PRIMARY)
        assert agent.agent_type == "protocol"
        assert agent.estimate_cost(CONTEXT) == 0.01
        assert ProtocolAgent(_LegacyAgent(), PRIMARY).estimate_cost(CONTEXT) == 0.0

    def test_legacy_agent_without_kwargs_supported(self):
        agent = ProtocolAgent(_LegacyAgent(), PRIMARY)
        result = agent.execute(CONTEXT, on_chunk=lambda text: None)
        assert result.output == "legacy"
        assert result.metadata["agentId"] == "finance-analyst"


class TestEscalation:
    def test_fallback_requires_descriptor(self):
        with pytest.raises(ValueError):
            ProtocolAgent(_StubAgent("x"), PRIMARY, fallback=_StubAgent("y"))

    def test_high_confidence_buffered_replay(self):
        inner = _StubAgent("jawaban kuat\n[[CONFIDENCE=0.9]]")
        fallback = _StubAgent("tidak dipakai")
        chunks = []
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT, on_chunk=chunks.append)
        assert result.output == "jawaban kuat"
        assert chunks == ["jawaban kuat"]  # replayed once, marker stripped
        assert inner.calls[0]["on_chunk"] is None  # buffered primary run
        assert fallback.calls == []
        assert result.metadata["confidence"] == 0.9
        assert "escalated" not in result.metadata

    def test_missing_marker_treated_as_confident(self):
        inner = _StubAgent("jawaban tanpa marker")
        fallback = _StubAgent("tidak dipakai")
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT)
        assert result.output == "jawaban tanpa marker"
        assert fallback.calls == []
        assert "confidence" not in result.metadata

    def test_low_confidence_escalates(self):
        inner = _StubAgent("jawaban lemah\n[[CONFIDENCE=0.2]]")
        fallback = _StubAgent("jawaban senior\n[[CONFIDENCE=0.95]]")
        chunks, events = [], []
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT, on_chunk=chunks.append, on_progress=events.append)
        # Fallback answer wins, its own marker also stripped.
        assert result.output == "jawaban senior"
        assert result.metadata["escalated"] is True
        assert result.metadata["escalatedFrom"] == "finance-analyst"
        assert result.metadata["agentId"] == "senior-consultant"
        assert result.metadata["agentName"] == "Konsultan Senior"
        assert result.metadata["confidence"] == 0.2  # the primary's self-report
        # Fallback streamed live (raw chunk includes its marker; stripping
        # applies to the persisted output, not the live stream).
        assert fallback.calls[0]["on_chunk"] is not None
        # The weak primary answer never reached the user.
        assert all("lemah" not in chunk for chunk in chunks)
        phases = [event.phase for event in events]
        assert "Agen: Analis Keuangan" in phases
        assert "Eskalasi ke Konsultan Senior" in phases

    def test_low_confidence_rolls_back_primary_memory(self):
        inner = _StubAgent("lemah\n[[CONFIDENCE=0.1]]")
        fallback = _StubAgent("senior")
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        agent.execute(CONTEXT)
        assert inner.memory.truncated_to == 1  # back to pre-turn length
        assert inner.memory.messages == ["system"]

    def test_threshold_boundary_is_not_escalated(self):
        inner = _StubAgent("pas\n[[CONFIDENCE=0.5]]")
        fallback = _StubAgent("tidak dipakai")
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT)
        assert result.output == "pas"
        assert fallback.calls == []

    def test_custom_threshold(self):
        inner = _StubAgent("cukup\n[[CONFIDENCE=0.6]]")
        fallback = _StubAgent("senior")
        agent = ProtocolAgent(
            inner,
            PRIMARY,
            fallback=fallback,
            fallback_descriptor=FALLBACK,
            confidence_threshold=0.7,
        )
        result = agent.execute(CONTEXT)
        assert result.metadata["escalated"] is True
        assert result.output == "senior"

    def test_single_hop_fallback_marker_not_acted_on(self):
        """The fallback's own low confidence never triggers another hop."""
        inner = _StubAgent("lemah\n[[CONFIDENCE=0.1]]")
        fallback = _StubAgent("ragu juga\n[[CONFIDENCE=0.1]]")
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT)
        assert result.output == "ragu juga"
        assert len(fallback.calls) == 1

    def test_rollback_absent_memory_is_harmless(self):
        inner = _StubAgent("lemah\n[[CONFIDENCE=0.1]]", with_memory=False)
        fallback = _StubAgent("senior")
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT)
        assert result.output == "senior"

    def test_rollback_failure_is_swallowed(self):
        inner = _StubAgent("lemah\n[[CONFIDENCE=0.1]]")

        def broken(length):
            raise RuntimeError("db gone")

        inner.memory.truncate_to = broken
        fallback = _StubAgent("senior")
        agent = ProtocolAgent(inner, PRIMARY, fallback=fallback, fallback_descriptor=FALLBACK)
        result = agent.execute(CONTEXT)
        assert result.output == "senior"
        assert result.metadata["escalated"] is True
