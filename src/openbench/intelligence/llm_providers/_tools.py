"""Gemini tool-call conversion and normalization helpers."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from openbench.mcp.schema import normalize_provider_json_schema

logger = logging.getLogger(__name__)


class _GeminiToolConversionMixin:
    """Mixin for GeminiLLMProvider; not instantiated directly."""

    @staticmethod
    def _normalize_tool_arg_value(value: Any) -> Any:
        """Convert SDK/proto/Pydantic values into stable JSON-like values."""
        if hasattr(value, "model_dump"):
            try:
                value = value.model_dump(by_alias=True, exclude_none=True)
            except TypeError:
                value = value.model_dump()
            except Exception:
                pass
        elif hasattr(value, "dict") and not isinstance(value, dict):
            try:
                value = value.dict()
            except Exception:
                pass

        if isinstance(value, Mapping):
            return {
                str(key): _GeminiToolConversionMixin._normalize_tool_arg_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [_GeminiToolConversionMixin._normalize_tool_arg_value(item) for item in value]
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        try:
            return json.loads(json.dumps(value, default=str, allow_nan=False))
        except (TypeError, ValueError):
            return str(value)

    @classmethod
    def _normalize_tool_args(cls, args: Any) -> dict[str, Any]:
        """Return a stable dict for Gemini/OpenAI-style tool arguments."""
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                return {"raw": args}

        if hasattr(args, "model_dump"):
            try:
                args = args.model_dump(by_alias=True, exclude_none=True)
            except TypeError:
                args = args.model_dump()
            except Exception:
                pass

        if not isinstance(args, Mapping) and hasattr(args, "items"):
            try:
                args = dict(args.items())
            except Exception:
                pass

        if not isinstance(args, Mapping):
            return {}

        normalized = cls._normalize_tool_arg_value(args)
        return normalized if isinstance(normalized, dict) else {}

    @classmethod
    def _normalized_tool_call_signature(
        cls, tool_call: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(name, args)`` for either flat or OpenAI-style tool calls."""
        if "function" in tool_call:
            func = tool_call.get("function") or {}
            name = str(func.get("name") or "")
            args = func.get("arguments", {})
        else:
            name = str(tool_call.get("name") or "")
            args = tool_call.get("arguments", {})
        return name, cls._normalize_tool_args(args)

    @staticmethod
    def _tool_call_id(tool_call: dict[str, Any]) -> str | None:
        """Return the persisted OpenAI-style tool call id, when available."""
        tc_id = tool_call.get("id")
        return tc_id if isinstance(tc_id, str) and tc_id else None

    @classmethod
    def _raw_content_matches_tool_calls(
        cls,
        raw_content: Any,
        tool_calls: list[dict[str, Any]] | None,
    ) -> bool:
        """Return True when raw Gemini content can be safely replayed.

        For assistant tool-call turns, Gemini requires the replayed model
        content to contain exactly the function calls that the following
        function_response turns answer. A partial raw streaming chunk is worse
        than no raw content, so only raw content with matching count, name, and
        args is safe to replay.
        """
        parts = getattr(raw_content, "parts", None) or []
        raw_calls: list[tuple[str, dict[str, Any]]] = []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if not fc:
                continue
            raw_calls.append(
                (
                    str(getattr(fc, "name", "") or ""),
                    cls._normalize_tool_args(getattr(fc, "args", {}) or {}),
                )
            )

        expected = [
            cls._normalized_tool_call_signature(tc)
            for tc in (tool_calls or [])
            if isinstance(tc, dict)
        ]
        if expected:
            return raw_calls == expected
        return not raw_calls

    @classmethod
    def _merge_tool_call_raw_content(
        cls,
        chunks: list[Any],
        tool_calls: list[dict[str, Any]],
    ) -> Any | None:
        """Build replayable Gemini model content from streamed tool-call chunks.

        Gemini may split several function_call parts across stream chunks.
        Replaying only the first chunk drops later calls; rebuilding from the
        generic tool_calls drops Gemini's thought_signature metadata. Instead,
        keep the original SDK Part objects and merge just the function_call
        parts into one model Content for the next request in the same agent
        turn.
        """
        if not chunks:
            return None

        merged_parts: list[Any] = []
        for chunk in chunks:
            candidates = getattr(chunk, "candidates", None) or []
            if not candidates:
                continue
            content = getattr(candidates[0], "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "function_call", None):
                    merged_parts.append(part)

        if not merged_parts:
            return None

        from google.genai import types

        try:
            raw_content = types.Content(role="model", parts=merged_parts)
        except Exception:
            # Tests may use lightweight mocks instead of SDK Part objects.
            raw_content = SimpleNamespace(role="model", parts=merged_parts)

        if cls._raw_content_matches_tool_calls(raw_content, tool_calls):
            return raw_content
        return None

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list:
        """Convert OpenAI-style tool schemas to Gemini FunctionDeclarations.

        BaseAgent tools.get_schemas() returns:
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]

        Gemini expects:
            [types.Tool(function_declarations=[types.FunctionDeclaration(...)])]

        Args:
            tools: OpenAI-format tool schema list.

        Returns:
            List with a single types.Tool containing all FunctionDeclarations.
        """
        from google.genai import types

        declarations = []
        for tool in tools:
            func = tool.get("function", tool)
            name = str(func.get("name") or "")
            try:
                declarations.append(
                    types.FunctionDeclaration(
                        name=name,
                        description=func.get("description", ""),
                        parameters=normalize_provider_json_schema(func.get("parameters")),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Skipping tool %s because its schema is not accepted by Gemini: %s",
                    name or "<unnamed>",
                    exc,
                )

        if not declarations:
            return []

        return [types.Tool(function_declarations=declarations)]
