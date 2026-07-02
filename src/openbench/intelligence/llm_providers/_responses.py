"""Gemini response part extraction (text, tool calls, debug)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class _GeminiResponseMixin:
    """Mixin for GeminiLLMProvider; not instantiated directly."""

    @staticmethod
    def _extract_text_from_parts(response: Any) -> str:
        """Extract only answer text from response parts.

        Filters out:
        - function_call parts (tool invocations)
        - thought parts (Gemini 3+ thinking/reasoning content)

        Avoids the Gemini SDK warning "there are non-text parts in the
        response" that fires when accessing .text on chunks that contain
        both text and function_call parts.

        Args:
            response: Gemini API response or stream chunk.

        Returns:
            Concatenated text from all answer-text parts (excludes thoughts).
        """
        if not hasattr(response, "candidates") or not response.candidates:
            return ""

        candidate = response.candidates[0]
        if not hasattr(candidate, "content") or not candidate.content:
            return ""

        parts = candidate.content.parts
        if not parts:
            return ""

        text_parts = [
            part.text
            for part in parts
            if (
                hasattr(part, "text")
                and part.text
                and not (hasattr(part, "function_call") and part.function_call)
                and not getattr(part, "thought", False)
            )
        ]

        return "".join(text_parts)

    def _extract_tool_calls(self, response, id_offset: int = 0) -> list[dict[str, Any]]:
        """Extract tool calls from a Gemini response or stream chunk.

        Converts Gemini's function_calls to the dict format that
        BaseAgent._parse_tool_calls() expects.

        Args:
            response: Gemini API response or stream chunk.
            id_offset: Starting index for generated ``call_<n>`` ids.
                Used when accumulating tool calls across stream chunks
                so each call gets a unique id.

        Returns:
            List of tool call dicts with id, name, arguments.
        """
        tool_calls: list[dict[str, Any]] = []
        if not hasattr(response, "candidates") or not response.candidates:
            return tool_calls

        candidate = response.candidates[0]
        if not hasattr(candidate, "content") or not candidate.content:
            return tool_calls

        for i, part in enumerate(candidate.content.parts):
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(
                    {
                        "id": f"call_{id_offset + i}",
                        "name": fc.name,
                        "arguments": self._normalize_tool_args(fc.args if fc.args else {}),
                    }
                )

        return tool_calls

    @staticmethod
    def _describe_response_parts(response: Any) -> dict[str, Any]:
        """Summarize what parts a Gemini response/chunk actually contains.

        Used by the "no text output" diagnostic path so we can tell
        *why* a response looked empty — was it filtered thoughts, a
        safety block, a truncated generation, or something else?

        Returns a dict with:
            - finish_reason: str | None
            - block_reason: str | None   (from prompt_feedback)
            - part_types: dict[str, int] counts of text / function_call /
                          thought / inline_data / executable_code / other
            - has_thought_signature: bool
        """
        out: dict[str, Any] = {
            "finish_reason": None,
            "block_reason": None,
            "part_types": {
                "text": 0,
                "function_call": 0,
                "thought": 0,
                "inline_data": 0,
                "executable_code": 0,
                "other": 0,
            },
            "has_thought_signature": False,
        }

        # Prompt-level block (safety, recitation, etc.)
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None:
            br = getattr(feedback, "block_reason", None)
            if br:
                out["block_reason"] = str(br)

        if not hasattr(response, "candidates") or not response.candidates:
            return out

        candidate = response.candidates[0]

        fr = getattr(candidate, "finish_reason", None)
        if fr is not None:
            out["finish_reason"] = str(fr)

        content = getattr(candidate, "content", None)
        if content is None:
            return out

        parts = getattr(content, "parts", None) or []
        for part in parts:
            if getattr(part, "thought", False):
                out["part_types"]["thought"] += 1
            elif getattr(part, "function_call", None):
                out["part_types"]["function_call"] += 1
            elif getattr(part, "text", None):
                out["part_types"]["text"] += 1
            elif getattr(part, "inline_data", None):
                out["part_types"]["inline_data"] += 1
            elif getattr(part, "executable_code", None):
                out["part_types"]["executable_code"] += 1
            else:
                out["part_types"]["other"] += 1
            if getattr(part, "thought_signature", None):
                out["has_thought_signature"] = True

        return out
