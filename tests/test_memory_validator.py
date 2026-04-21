"""Tests for the orphan tool_call validator."""

from __future__ import annotations

import logging

import pytest

from openbench.intelligence.memory_validator import (
    ValidationDrop,
    validate_tool_call_pairs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(content: str = "hi") -> dict:
    return {"role": "user", "content": content}


def _assistant_text(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _assistant_calls(
    calls: list[dict], content: str = "", raw_content: object | None = None
) -> dict:
    msg: dict = {"role": "assistant", "content": content, "tool_calls": calls}
    if raw_content is not None:
        msg["raw_content"] = raw_content
    return msg


def _tool_call(id_: str, name: str = "do_thing", args: dict | None = None) -> dict:
    return {"id": id_, "name": name, "arguments": args or {}}


def _tool_response(id_: str, name: str = "do_thing", content: str = "{}") -> dict:
    return {
        "role": "tool",
        "tool_call_id": id_,
        "name": name,
        "content": content,
    }


# ---------------------------------------------------------------------------
# Layer 1 validator — 7 tests per RFC-TOOL-CALL-INTEGRITY §4.4
# ---------------------------------------------------------------------------


class TestValidator:
    def test_drops_orphan_tool_call(self):
        """Single assistant tool_call with no matching tool response → dropped."""
        messages = [
            _user("analyze"),
            _assistant_calls([_tool_call("call_1")], content="I'll do it"),
            # tool response missing — simulates mid-turn crash
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        assert len(drops) == 1
        assert drops[0].reason == "orphan_tool_call"
        assert drops[0].tool_call_id == "call_1"

        # Assistant kept (has content text) but tool_calls filtered empty
        assert cleaned[1]["role"] == "assistant"
        assert cleaned[1]["tool_calls"] == []
        assert cleaned[1]["content"] == "I'll do it"

    def test_drops_orphan_tool_response(self):
        """Tool response with no preceding assistant call → dropped."""
        messages = [
            _user("analyze"),
            _assistant_text("Done"),
            _tool_response("call_ghost"),  # orphan
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        assert len(drops) == 1
        assert drops[0].reason == "orphan_tool_response"
        assert drops[0].tool_call_id == "call_ghost"

        # Tool message dropped; user + assistant kept
        assert [m["role"] for m in cleaned] == ["user", "assistant"]

    def test_handles_parallel_tool_calls_partial(self):
        """3 calls, only 2 responses → keep 2 valid calls + 2 responses,
        drop the 1 orphan. Parallel tool calls matter; dropping all three
        would lose valid context."""
        messages = [
            _user("multi-task"),
            _assistant_calls(
                [
                    _tool_call("call_a"),
                    _tool_call("call_b"),
                    _tool_call("call_c"),
                ]
            ),
            _tool_response("call_a"),
            _tool_response("call_b"),
            # call_c response missing
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        orphan_drops = [d for d in drops if d.reason == "orphan_tool_call"]
        assert len(orphan_drops) == 1
        assert orphan_drops[0].tool_call_id == "call_c"

        assistant = cleaned[1]
        kept_ids = [tc["id"] for tc in assistant["tool_calls"]]
        assert kept_ids == ["call_a", "call_b"]

        # Both valid tool responses preserved
        tool_msgs = [m for m in cleaned if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["call_a", "call_b"]

    def test_drops_empty_assistant_after_all_calls_removed(self):
        """Assistant with only orphan tool_calls and no text → entire message
        dropped. Keeping an empty assistant would confuse the LLM."""
        messages = [
            _user("hi"),
            _assistant_calls([_tool_call("call_x")], content=""),
            # no tool response and no content
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        reasons = {d.reason for d in drops}
        assert "orphan_tool_call" in reasons
        assert "empty_assistant_after_drop" in reasons

        # Only the user message remains
        assert len(cleaned) == 1
        assert cleaned[0]["role"] == "user"

    def test_preserves_valid_history(self):
        """Fully paired assistant/tool sequence — validator is a no-op."""
        messages = [
            _user("analyze"),
            _assistant_calls([_tool_call("call_1"), _tool_call("call_2")]),
            _tool_response("call_1"),
            _tool_response("call_2"),
            _assistant_text("Here are results"),
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        assert drops == []
        # Same length and roles in same order
        assert len(cleaned) == len(messages)
        assert [m["role"] for m in cleaned] == [m["role"] for m in messages]

    def test_clears_raw_content_when_tool_calls_filtered(self):
        """raw_content carries the original LLM response which may include
        function_call parts for orphan ids — clear it to prevent re-leaking
        the orphan via the raw_content fast path in _convert_messages."""
        sentinel_raw = object()
        messages = [
            _user("hi"),
            _assistant_calls(
                [_tool_call("call_valid"), _tool_call("call_orphan")],
                content="working",
                raw_content=sentinel_raw,
            ),
            _tool_response("call_valid"),
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        assistant = cleaned[1]
        assert "raw_content" not in assistant
        assert [tc["id"] for tc in assistant["tool_calls"]] == ["call_valid"]
        assert len(drops) == 1

    def test_leaves_raw_content_intact_when_no_filtering(self):
        """If every tool_call has a matching response, raw_content stays."""
        sentinel_raw = object()
        messages = [
            _user("hi"),
            _assistant_calls(
                [_tool_call("call_1")],
                raw_content=sentinel_raw,
            ),
            _tool_response("call_1"),
        ]
        cleaned, drops = validate_tool_call_pairs(messages)

        assert drops == []
        assert cleaned[1]["raw_content"] is sentinel_raw


# ---------------------------------------------------------------------------
# Integration — validator gate via env var at _convert_messages
# ---------------------------------------------------------------------------


class TestConverterIntegration:
    def _build_provider_without_client(self):
        """Construct a GeminiLLMProvider without touching the real SDK client."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        return GeminiLLMProvider(model_name="gemini-3-flash-preview", api_key="fake")

    def test_validator_runs_by_default(self, monkeypatch, caplog):
        """With no env var set, validator should drop orphans and log."""
        monkeypatch.delenv("OPENBENCH_MEMORY_VALIDATOR", raising=False)
        provider = self._build_provider_without_client()

        messages = [
            _user("go"),
            _assistant_calls([_tool_call("orphan_1")], content="doing"),
        ]
        with caplog.at_level(logging.WARNING, logger="openbench.intelligence.llm_providers"):
            _system, contents = provider._convert_messages(messages)

        # Warning emitted for the orphan
        assert any("memory-validator" in r.message for r in caplog.records)
        # Gemini contents contain user + assistant-text-only (no function_call parts)
        user_c, assistant_c = contents
        assert user_c.role == "user"
        assert assistant_c.role == "model"
        # Assistant part should have text only, no function_call
        part = assistant_c.parts[0]
        assert getattr(part, "function_call", None) is None

    def test_validator_disabled_by_env(self, monkeypatch, caplog):
        """With OPENBENCH_MEMORY_VALIDATOR=0, validator is bypassed.

        The orphan tool_call survives into the Gemini contents, which is
        exactly the pre-fix behaviour (Gemini would reject it at the API).
        """
        monkeypatch.setenv("OPENBENCH_MEMORY_VALIDATOR", "0")
        provider = self._build_provider_without_client()

        messages = [
            _user("go"),
            _assistant_calls([_tool_call("orphan_1", name="do_thing")], content="doing"),
        ]
        with caplog.at_level(logging.WARNING, logger="openbench.intelligence.llm_providers"):
            _system, contents = provider._convert_messages(messages)

        # No validator log
        assert not any("memory-validator" in r.message for r in caplog.records)
        # Assistant content includes the (orphan) function_call part
        assistant_c = contents[1]
        assert any(getattr(p, "function_call", None) is not None for p in assistant_c.parts)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_validation_drop_is_frozen_dataclass():
    """ValidationDrop must be hashable/frozen so callers can put them in sets."""
    from dataclasses import FrozenInstanceError

    d = ValidationDrop(
        reason="orphan_tool_call",
        message_index=0,
        tool_call_id="x",
        detail="",
    )
    with pytest.raises(FrozenInstanceError):
        d.reason = "other"  # type: ignore[misc]
