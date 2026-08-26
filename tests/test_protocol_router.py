"""Tests for the agent protocol LLM router."""

import pytest

from openbench.intelligence.protocol import AgentDescriptor, AgentDirectory
from openbench.intelligence.protocol.router import RouteDecision, build_router_prompt, route


def _directory() -> AgentDirectory:
    directory = AgentDirectory()
    directory.register(
        AgentDescriptor(
            id="finance-analyst",
            name="Analis Keuangan",
            description="Laporan keuangan, anggaran, pajak, arus kas.",
        ),
        lambda: None,
    )
    directory.register(
        AgentDescriptor(
            id="legal-reviewer",
            name="Peninjau Legal",
            description="Kontrak, kepatuhan, regulasi.",
        ),
        lambda: None,
    )
    return directory


class TestBuildRouterPrompt:
    def test_lists_all_descriptors(self):
        prompt = build_router_prompt("berapa pajak saya?", _directory().descriptors())
        assert "finance-analyst — Analis Keuangan: Laporan keuangan" in prompt
        assert "legal-reviewer — Peninjau Legal: Kontrak" in prompt
        assert "berapa pajak saya?" in prompt
        assert '{"agent": "<agent-id>"}' in prompt

    def test_message_truncated(self):
        prompt = build_router_prompt("x" * 5000, _directory().descriptors(), max_message_chars=100)
        assert "x" * 100 in prompt
        assert "x" * 101 not in prompt

    def test_blank_description_placeholder(self):
        descriptors = [AgentDescriptor(id="a", name="A", description="  ")]
        assert "- a — A: (no description)" in build_router_prompt("hi", descriptors)


class TestRoute:
    def test_happy_path_json(self):
        decision = route("pajak?", _directory(), lambda prompt: '{"agent": "finance-analyst"}')
        assert decision == RouteDecision("finance-analyst", reason="router: JSON match")

    def test_null_means_default(self):
        decision = route("halo", _directory(), lambda prompt: '{"agent": null}')
        assert decision.agent_id is None
        assert decision.fallback_used is False

    def test_fenced_json_accepted(self):
        reply = '```json\n{"agent": "legal-reviewer"}\n```'
        decision = route("kontrak", _directory(), lambda prompt: reply)
        assert decision.agent_id == "legal-reviewer"

    def test_junk_reply_falls_back(self):
        decision = route("hi", _directory(), lambda prompt: "I think maybe finance? or legal?")
        assert decision.agent_id is None
        assert decision.fallback_used is True

    def test_plain_text_single_id_scan(self):
        decision = route("hi", _directory(), lambda prompt: "finance-analyst")
        assert decision.agent_id == "finance-analyst"
        assert decision.fallback_used is False

    def test_unknown_id_falls_back(self):
        decision = route("hi", _directory(), lambda prompt: '{"agent": "nonexistent"}')
        assert decision.agent_id is None
        assert decision.fallback_used is True

    def test_llm_exception_falls_back(self):
        def broken(prompt: str) -> str:
            raise RuntimeError("boom")

        decision = route("hi", _directory(), broken)
        assert decision.agent_id is None
        assert decision.fallback_used is True

    def test_empty_reply_falls_back(self):
        decision = route("hi", _directory(), lambda prompt: "")
        assert decision.agent_id is None
        assert decision.fallback_used is True

    def test_empty_directory_skips_llm(self):
        calls = []

        def complete(prompt: str) -> str:
            calls.append(prompt)
            return '{"agent": null}'

        decision = route("hi", AgentDirectory(), complete)
        assert decision.agent_id is None
        assert decision.fallback_used is False
        assert calls == []

    def test_non_string_agent_value_falls_back(self):
        decision = route("hi", _directory(), lambda prompt: '{"agent": 42}')
        assert decision.agent_id is None
        assert decision.fallback_used is True

    @pytest.mark.parametrize(
        "reply",
        ['{"agent": "finance-analyst"}', '  {"agent": "finance-analyst"}  '],
    )
    def test_whitespace_tolerated(self, reply):
        assert route("hi", _directory(), lambda prompt: reply).agent_id == "finance-analyst"
