"""Validator that strips orphan tool-call structures before LLM conversion.

``AgentMemory`` rows get written per message, so a process kill between
``add_assistant(tool_calls=...)`` and the following ``add_tool_result`` calls
leaves the SQLite memory with an assistant turn whose function calls have no
matching tool responses. Gemini rejects that sequence at the wire level with
``400 INVALID_ARGUMENT / "function call turn must come immediately after a
user turn or after a function response turn"``.

This module runs at the LLM-provider boundary (read side) and removes:

- Orphan entries in an assistant message's ``tool_calls`` (per-entry for
  parallel tool call tolerance — keep the calls whose responses exist,
  drop the ones that don't)
- Entire assistant messages that would end up with no text and no
  tool_calls after the filter
- Orphan tool-role messages (a tool response whose id has no matching
  assistant call)

Pairing is done by ``id`` (OpenAI-style ``tool_call_id``). Message order
is not enforced — if a tool response appears before its call in the list
the pairing still counts; out-of-order sequences are rare and a separate
concern from orphan handling.

The validator is pure and side-effect-free. Callers decide how to log,
count, or propagate the returned :class:`ValidationDrop` entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "ValidationDrop",
    "validate_tool_call_pairs",
]


DropReason = Literal[
    "orphan_tool_call",
    "empty_assistant_after_drop",
    "orphan_tool_response",
]


@dataclass(frozen=True)
class ValidationDrop:
    """Report of a single message or tool_call entry that was removed."""

    reason: DropReason
    message_index: int
    tool_call_id: str | None
    detail: str


def _extract_tool_call_id(tc: dict[str, Any]) -> str | None:
    """Return the OpenAI-style id of a tool_call entry.

    Handles both the flat shape ``{"id": ..., "name": ...}`` and the
    nested wire shape ``{"id": ..., "function": {"name": ...}}``.
    """
    tc_id = tc.get("id")
    return tc_id if isinstance(tc_id, str) and tc_id else None


def validate_tool_call_pairs(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ValidationDrop]]:
    """Remove orphan tool_calls and orphan tool responses from ``messages``.

    Args:
        messages: OpenAI-style message dicts, same shape the
            ``LLMProvider._convert_messages`` methods receive.

    Returns:
        A tuple ``(cleaned_messages, drops)``. ``cleaned_messages`` is a
        new list — the input is not mutated. ``drops`` lists every
        removal so the caller can log / count them.
    """
    # Pass 1: collect every tool_call_id that has a matching tool-role response.
    matched_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tcid = msg.get("tool_call_id")
            if isinstance(tcid, str) and tcid:
                matched_ids.add(tcid)

    cleaned: list[dict[str, Any]] = []
    drops: list[ValidationDrop] = []

    # Pass 2: filter orphan tool_calls inside each assistant message. If an
    # assistant ends up with empty content AND empty tool_calls, drop the
    # whole message.
    for idx, msg in enumerate(messages):
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            cleaned.append(msg)
            continue

        original_calls = msg["tool_calls"]
        kept: list[dict[str, Any]] = []
        for tc in original_calls:
            tc_id = _extract_tool_call_id(tc)
            if tc_id is not None and tc_id in matched_ids:
                kept.append(tc)
            else:
                drops.append(
                    ValidationDrop(
                        reason="orphan_tool_call",
                        message_index=idx,
                        tool_call_id=tc_id,
                        detail=(
                            f"assistant tool_call id={tc_id!r} has no matching "
                            "tool response; dropped"
                        ),
                    )
                )

        if not kept and not msg.get("content"):
            drops.append(
                ValidationDrop(
                    reason="empty_assistant_after_drop",
                    message_index=idx,
                    tool_call_id=None,
                    detail=(
                        "assistant message has no text content and all tool_calls "
                        "were orphan; entire message dropped"
                    ),
                )
            )
            continue

        if len(kept) != len(original_calls):
            # Rebuild the message. Drop raw_content because it was the
            # original LLM response that carried the orphan function_call
            # parts — keeping it would re-leak the orphan to Gemini even
            # though we fixed the tool_calls field. Losing thought
            # signatures is an acceptable trade for integrity.
            new_msg = dict(msg)
            new_msg["tool_calls"] = kept
            new_msg.pop("raw_content", None)
            cleaned.append(new_msg)
        else:
            cleaned.append(msg)

    # Pass 3: drop orphan tool responses. Build the set of ids that still
    # appear in an assistant tool_calls after filtering, then discard any
    # tool-role message whose id is not in that set.
    call_ids_in_assistants: set[str] = set()
    for msg in cleaned:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = _extract_tool_call_id(tc)
                if tc_id is not None:
                    call_ids_in_assistants.add(tc_id)

    final: list[dict[str, Any]] = []
    for idx, msg in enumerate(cleaned):
        if msg.get("role") == "tool":
            tcid = msg.get("tool_call_id")
            if isinstance(tcid, str) and tcid and tcid not in call_ids_in_assistants:
                drops.append(
                    ValidationDrop(
                        reason="orphan_tool_response",
                        message_index=idx,
                        tool_call_id=tcid,
                        detail=(
                            f"tool response id={tcid!r} has no matching assistant call; dropped"
                        ),
                    )
                )
                continue
        final.append(msg)

    return final, drops
