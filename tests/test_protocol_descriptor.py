"""Tests for the agent protocol descriptor and directory primitives."""

import threading

import pytest

from openbench.intelligence.protocol import (
    AgentDescriptor,
    AgentDirectory,
    AgentRequest,
    AgentResponse,
)


def _descriptor(agent_id: str = "finance-analyst", **overrides):
    values = {
        "id": agent_id,
        "name": "Analis Keuangan",
        "description": "Laporan keuangan, anggaran, pajak.",
    }
    values.update(overrides)
    return AgentDescriptor(**values)


class TestAgentDescriptor:
    def test_fields_round_trip(self):
        descriptor = _descriptor(tags=("finance", "tax"), model="gemini-2.5-pro")
        assert descriptor.id == "finance-analyst"
        assert descriptor.name == "Analis Keuangan"
        assert descriptor.tags == ("finance", "tax")
        assert descriptor.model == "gemini-2.5-pro"

    def test_is_frozen(self):
        descriptor = _descriptor()
        with pytest.raises(AttributeError):
            descriptor.name = "other"  # type: ignore[misc]

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError):
            AgentDescriptor(id="  ", name="X")

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            AgentDescriptor(id="x", name="")


class TestAgentDirectory:
    def test_register_get_resolve(self):
        directory = AgentDirectory()
        sentinel = object()
        directory.register(_descriptor(), lambda: sentinel)
        assert directory.get("finance-analyst") == _descriptor()
        assert directory.resolve("finance-analyst") is sentinel
        assert "finance-analyst" in directory
        assert len(directory) == 1

    def test_resolve_is_lazy_and_cached(self):
        directory = AgentDirectory()
        calls = []
        directory.register(_descriptor(), lambda: calls.append(1) or object())
        assert calls == []  # nothing built at registration
        first = directory.resolve("finance-analyst")
        second = directory.resolve("finance-analyst")
        assert first is second
        assert calls == [1]

    def test_duplicate_id_raises(self):
        directory = AgentDirectory()
        directory.register(_descriptor(), lambda: None)
        with pytest.raises(ValueError):
            directory.register(_descriptor(), lambda: None)

    def test_unregister(self):
        directory = AgentDirectory()
        directory.register(_descriptor(), lambda: None)
        assert directory.unregister("finance-analyst") is True
        assert directory.unregister("finance-analyst") is False
        assert directory.get("finance-analyst") is None
        assert directory.resolve("finance-analyst") is None
        assert len(directory) == 0

    def test_descriptors_in_registration_order(self):
        directory = AgentDirectory()
        directory.register(_descriptor("b-agent", name="B"), lambda: None)
        directory.register(_descriptor("a-agent", name="A"), lambda: None)
        assert [d.id for d in directory.descriptors()] == ["b-agent", "a-agent"]

    def test_unknown_id_lookups(self):
        directory = AgentDirectory()
        assert directory.get("missing") is None
        assert directory.resolve("missing") is None
        assert "missing" not in directory

    def test_concurrent_registration_smoke(self):
        directory = AgentDirectory()

        def register(index: int) -> None:
            directory.register(_descriptor(f"agent-{index}", name=f"A{index}"), lambda: index)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(directory) == 20


class TestEnvelope:
    def test_request_defaults(self):
        request = AgentRequest(message="hitung pajak")
        assert request.sender == "user"
        assert request.recipient == ""
        assert request.metadata == {}

    def test_response_metadata_minimal(self):
        response = AgentResponse(text="jawaban", agent_id="finance-analyst")
        assert response.to_metadata() == {
            "agentId": "finance-analyst",
            "agentName": "finance-analyst",
        }

    def test_response_metadata_full(self):
        response = AgentResponse(
            text="jawaban",
            agent_id="senior-consultant",
            agent_name="Konsultan Senior",
            confidence=0.3,
            escalated=True,
            escalated_from="finance-analyst",
        )
        assert response.to_metadata() == {
            "agentId": "senior-consultant",
            "agentName": "Konsultan Senior",
            "confidence": 0.3,
            "escalated": True,
            "escalatedFrom": "finance-analyst",
        }

    def test_response_metadata_omits_falsy_extras(self):
        response = AgentResponse(
            text="jawaban", agent_id="a", agent_name="A", confidence=None, escalated=False
        )
        metadata = response.to_metadata()
        assert "confidence" not in metadata
        assert "escalated" not in metadata
        assert "escalatedFrom" not in metadata
