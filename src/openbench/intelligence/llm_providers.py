"""Concrete LLM provider implementations.

Provides the missing concrete LLMProvider that BaseAgent needs to run
its reasoning loop via ProviderService.resolve() → LLMProviderRegistry.create().

Currently implemented:
- GeminiLLMProvider: Google Gemini models via google-genai SDK

Usage:
    # Auto-registered on import — just configure a provider:
    from openbench.core.providers import configure_provider, ProviderType

    configure_provider(
        name="gemini",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": "your-key"},
        is_default=True,
    )

    # Then BaseAgent resolves it automatically:
    agent = BaseAgent(goal="Analyze data", model="gemini-2.5-flash")
    result = agent.execute(context)
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections.abc import Mapping
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from openbench.core.abstractions import LLMProvider, LLMResponse
from openbench.core.constants import DEFAULT_MAX_RETRIES
from openbench.intelligence.memory_validator import validate_tool_call_pairs
from openbench.mcp.schema import normalize_provider_json_schema

logger = logging.getLogger(__name__)


def _memory_validator_enabled() -> bool:
    """Gate the orphan-tool-call validator via env var.

    Default ``"1"`` (on). Set ``OPENBENCH_MEMORY_VALIDATOR=0`` to bypass
    when debugging a suspected false-positive drop.
    """
    flag = os.environ.get("OPENBENCH_MEMORY_VALIDATOR", "1").strip().lower()
    return flag in ("1", "true", "yes", "on")


# Cost per 1M tokens in USD (converted to per-1K for compatibility with config.py)
_GEMINI_COSTS: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
}


class GeminiLLMProvider(LLMProvider):
    """Concrete Gemini LLM provider using google-genai SDK.

    Bridges the gap between BaseAgent's reasoning loop and Google's Gemini API.

    Handles:
    - Message format conversion (OpenAI-style → Gemini Content/Part)
    - Tool schema conversion (OpenAI function format → Gemini FunctionDeclaration)
    - Tool call response parsing (Gemini function_calls → dict for _parse_tool_calls)
    - Token usage tracking and cost estimation

    Args:
        api_key: Google API key. Falls back to GOOGLE_API_KEY env var.
        model: Default model ID (default: "gemini-2.5-flash").
        temperature: Default generation temperature (default: 0.7).
        max_output_tokens: Default max output tokens (default: 8192).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
        **kwargs,
    ):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._client = None
        # Cache of Files-API uploads keyed by (path, size, mtime) so re-asking
        # about the same large video/audio doesn't re-upload every turn.
        self._files_cache: dict[tuple, Any] = {}

    # Files <= this size are sent inline as bytes; larger payloads go through
    # the Gemini Files API. Gemini's inline request cap is ~20 MB; stay under it.
    _INLINE_MEDIA_LIMIT = 18 * 1024 * 1024

    @property
    def provider_name(self) -> str:
        """Provider name identifier."""
        return "gemini"

    def _get_client(self):
        """Lazy-init google-genai Client."""
        if self._client is None:
            try:
                from google import genai
            except ImportError:
                raise ImportError(
                    "google-genai package required for GeminiLLMProvider. "
                    "Install with: pip install google-genai"
                ) from None

            if not self.api_key:
                raise ValueError(
                    "Google API key required. Set GOOGLE_API_KEY environment variable "
                    "or pass api_key to constructor."
                )

            self._client = genai.Client(api_key=self.api_key)

        return self._client

    def _convert_messages(self, messages: list[dict[str, Any]], model: str = "") -> tuple:
        """Convert OpenAI-style messages to Gemini format.

        BaseAgent sends messages as:
            [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]

        Gemini expects:
            system_instruction (str) + contents (list of Content objects)

        A user message may carry provider-neutral ``media`` references
        (:class:`~openbench.core.abstractions.MediaContent` dicts). This is the
        per-provider translation point: each LLMProvider turns those neutral
        references into its own SDK shape. Here they become Gemini ``Part``s
        (inline bytes for small files, Files-API URIs for large ones), gated by
        the active model's multimodal capability flags.

        Args:
            messages: OpenAI-style message list from AgentMemory.
            model: Active model id (for capability gating). Defaults to the
                instance model.

        Returns:
            Tuple of (system_instruction, contents) for Gemini API.
        """
        from google.genai import types

        if _memory_validator_enabled():
            messages, drops = validate_tool_call_pairs(messages)
            for drop in drops:
                logger.warning(
                    "[memory-validator] dropped %s at index %d (id=%s): %s",
                    drop.reason,
                    drop.message_index,
                    drop.tool_call_id,
                    drop.detail,
                )

        system_instruction = None
        contents = []
        skipped_tool_response_ids: set[str] = set()
        skipped_unidentified_tool_responses = 0

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "system":
                system_instruction = content

            elif role == "user":
                parts = [types.Part.from_text(text=content)]
                media = msg.get("media")
                if media:
                    parts.extend(self._build_media_parts(media, model or self.model))
                contents.append(types.Content(role="user", parts=parts))

            elif role == "assistant":
                tool_calls = msg.get("tool_calls") or []
                # Use raw content only when it is faithful to the parsed
                # tool_calls. Streaming Gemini can split function_call parts
                # across chunks; replaying the first raw chunk while sending
                # every tool response creates a Gemini-invalid sequence.
                raw_content = msg.get("raw_content")
                if raw_content is not None and self._raw_content_matches_tool_calls(
                    raw_content,
                    tool_calls,
                ):
                    contents.append(raw_content)
                    continue

                if tool_calls:
                    for tc in tool_calls:
                        tc_id = self._tool_call_id(tc)
                        if tc_id:
                            skipped_tool_response_ids.add(tc_id)
                        else:
                            skipped_unidentified_tool_responses += 1
                    logger.warning(
                        "Skipping Gemini assistant tool-call replay because matching raw_content "
                        "is unavailable. This avoids reconstructing function_call parts without "
                        "Gemini thought_signature metadata."
                    )
                    # Do not synthesize Gemini function_call parts from persisted
                    # generic tool_calls. Thinking models require the original
                    # thought_signature attached to the model's function_call part.
                    # The following tool-role messages are skipped by id below.
                    # Drop this assistant turn as a unit; it was an in-progress
                    # tool-call turn, not the final answer.
                    continue

                if content:
                    contents.append(
                        types.Content(
                            role="model",
                            parts=[types.Part.from_text(text=content)],
                        )
                    )

            elif role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id in skipped_tool_response_ids:
                    skipped_tool_response_ids.remove(tool_call_id)
                    continue
                if skipped_unidentified_tool_responses > 0:
                    skipped_unidentified_tool_responses -= 1
                    continue

                tool_name = msg.get("name", "")
                tool_content = content
                # Parse JSON content if possible
                if isinstance(tool_content, str):
                    try:
                        tool_content = json.loads(tool_content)
                    except (json.JSONDecodeError, TypeError):
                        tool_content = {"result": tool_content}
                if not isinstance(tool_content, dict):
                    tool_content = {"result": str(tool_content)}

                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tool_name,
                                response=tool_content,
                            )
                        ],
                    )
                )

        return system_instruction, contents

    def _model_supports_media(self, model: str, media_type: str) -> bool:
        """Whether ``model`` can natively consume ``media_type``.

        Reads the capability flags from the model registry. Unknown models are
        assumed capable (Gemini models are natively multimodal); a wrong guess
        is caught by the per-part try/except, which degrades to the text track.
        """
        try:
            from openbench.core.config import get_config

            info = get_config().get_model(model)
        except Exception:
            info = None
        if info is None:
            return True
        if media_type == "image":
            return info.supports_vision
        if media_type == "audio":
            return getattr(info, "supports_audio", False)
        if media_type == "video":
            return getattr(info, "supports_video", False)
        return False

    def _build_media_parts(self, media: list[dict[str, Any]], model: str) -> list:
        """Translate provider-neutral media references into Gemini Parts.

        Small files are sent inline as bytes; large files (video, long audio)
        go through the Files API. Any failure degrades gracefully — the part is
        skipped and the model still has the message text / extracted transcript.
        """
        from google.genai import types

        parts: list[Any] = []
        for item in media:
            media_type = item.get("type", "")
            mime = item.get("mime_type", "")
            path = item.get("path")
            if not path or not mime:
                continue
            if not self._model_supports_media(model, media_type):
                logger.info(
                    "Model %s does not support %s natively; relying on text track for %s",
                    model,
                    media_type,
                    item.get("metadata", {}).get("name", path),
                )
                continue
            try:
                import os as _os

                # Transcode video containers Gemini can't ingest (e.g. AVI).
                if media_type == "video":
                    from openbench.utils.media import ensure_video_for_gemini

                    path, mime = ensure_video_for_gemini(path, mime)

                size = _os.path.getsize(path)
                if size <= self._INLINE_MEDIA_LIMIT:
                    from pathlib import Path as _Path

                    parts.append(
                        types.Part.from_bytes(data=_Path(path).read_bytes(), mime_type=mime)
                    )
                else:
                    uploaded = self._upload_via_files_api(path, mime)
                    parts.append(
                        types.Part.from_uri(
                            file_uri=uploaded.uri,
                            mime_type=getattr(uploaded, "mime_type", mime),
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to attach media %s natively (%s); using text fallback",
                    path,
                    exc,
                )
        return parts

    def _upload_via_files_api(self, path: str, mime: str) -> Any:
        """Upload a large file via the Gemini Files API, cached per file.

        Cache key is (path, size, mtime) so an edited file re-uploads but the
        same file across turns is uploaded once. Waits briefly for video/audio
        that the API needs to process before it can be referenced.
        """
        import os as _os
        import time as _time

        stat = _os.stat(path)
        key = (path, stat.st_size, stat.st_mtime)
        cached = self._files_cache.get(key)
        if cached is not None:
            return cached

        client = self._get_client()
        uploaded = client.files.upload(file=path)

        # Files (esp. video) may need server-side processing before use.
        for _ in range(30):
            state = getattr(getattr(uploaded, "state", None), "name", None)
            if state != "PROCESSING":
                break
            _time.sleep(1)
            uploaded = client.files.get(name=uploaded.name)

        self._files_cache[key] = uploaded
        return uploaded

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
                str(key): GeminiLLMProvider._normalize_tool_arg_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [GeminiLLMProvider._normalize_tool_arg_value(item) for item in value]
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
    def _normalized_tool_call_signature(cls, tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in USD based on token usage.

        Args:
            model: Model name.
            prompt_tokens: Number of input tokens.
            completion_tokens: Number of output tokens.

        Returns:
            Estimated cost in USD.
        """
        costs = _GEMINI_COSTS.get(model)
        if not costs:
            return 0.0

        # Costs are per 1M tokens
        input_cost = (prompt_tokens / 1_000_000) * costs["input"]
        output_cost = (completion_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost

    @staticmethod
    def _parse_retry_delay(error: Exception) -> float | None:
        """Extract retry delay in seconds from a 429 error message."""
        msg = str(error)
        match = re.search(r"retry in ([\d.]+)s", msg, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None

    def _call_with_retry(
        self,
        client: Any,
        model: str,
        contents: Any,
        config: Any,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> Any:
        """Call Gemini API with retry on 429 RESOURCE_EXHAUSTED errors.

        Respects the API's suggested retryDelay when available,
        otherwise uses exponential backoff (15s, 30s, 60s).
        """
        fallback_delays = [15, 30, 60]
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                if not is_rate_limit or attempt >= max_retries:
                    raise

                last_error = e
                delay = self._parse_retry_delay(e)
                if delay is None:
                    delay = fallback_delays[min(attempt, len(fallback_delays) - 1)]

                logger.warning(
                    f"Rate limited (429). Retry {attempt + 1}/{max_retries} in {delay:.1f}s"
                )
                time.sleep(delay)

        raise last_error  # type: ignore[misc]  # pragma: no cover

    def generate(
        self,
        prompt: str | list[dict[str, Any]],
        model: str = "",
        **params,
    ) -> LLMResponse:
        """Generate text from prompt using Gemini.

        Handles both formats:
        - str: Simple text prompt (direct API call)
        - List[Dict]: OpenAI-style messages from BaseAgent (converted to Gemini format)

        Args:
            prompt: Input prompt string or message list.
            model: Model identifier (uses instance default if empty).
            **params: Additional parameters (tools, temperature, max_output_tokens).

        Returns:
            LLMResponse with generated text, token usage, and cost.
        """
        from google.genai import types

        client = self._get_client()
        model = model or self.model
        tools_param = params.pop("tools", None)
        temperature = params.pop("temperature", self.temperature)
        max_output_tokens = params.pop("max_output_tokens", self.max_output_tokens)

        # Handle str vs List[Dict]
        if isinstance(prompt, str):
            system_instruction = None
            contents = prompt
        else:
            system_instruction, contents = self._convert_messages(prompt, model=model)

        # Build generation config
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        if system_instruction:
            config.system_instruction = system_instruction

        if tools_param:
            config.tools = self._convert_tools(tools_param)

        # Call Gemini API with retry on 429 rate limit
        response = self._call_with_retry(client, model, contents, config)

        # Extract token usage
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = getattr(usage, "total_token_count", 0) or 0

        cost = self._estimate_cost(model, prompt_tokens, completion_tokens)

        # Extract text (may be empty if response has function calls)
        tool_calls = self._extract_tool_calls(response)
        text = ""
        if not tool_calls:
            # Use _extract_text_from_parts to filter thought parts (Gemini 3+)
            text = self._extract_text_from_parts(response)
            if not text:
                # Fallback to SDK .text property
                try:
                    text = response.text
                except Exception:
                    text = ""

        response_metadata: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

        # Same diagnostic as generate_stream: if we get nothing visible
        # back from the model, surface *why* — otherwise the caller just
        # sees an empty assistant turn with no clue what happened.
        if not text and not tool_calls:
            diagnostics = self._describe_response_parts(response)
            logger.warning(
                "Model %s returned no text output "
                "(prompt_tokens=%s, completion_tokens=%s, diagnostics=%s). "
                "This may be a Gemini 3 Confidence Dropout, a safety block, "
                "or a truncated reasoning turn.",
                model,
                prompt_tokens,
                completion_tokens,
                diagnostics,
            )
            response_metadata["empty_response_diagnostics"] = diagnostics

        llm_response = LLMResponse(
            text=text,
            model=model,
            tokens_used=total_tokens,
            cost=cost,
            metadata=response_metadata,
        )

        # Attach tool_calls for BaseAgent._parse_tool_calls()
        if tool_calls:
            llm_response.tool_calls = tool_calls

        # Store raw content for replay (preserves thought_signature for Gemini 2.5+)
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "content") and candidate.content:
                llm_response.raw_content = candidate.content

        return llm_response

    def generate_stream(
        self,
        prompt: str | list[dict[str, Any]],
        model: str = "",
        **params,
    ) -> Iterator[LLMResponse]:
        """Stream text chunks from Gemini using generate_content_stream().

        Yields partial LLMResponse objects with delta text. The final
        yielded response includes token usage and cost. Tool calls are
        detected on the last chunk and attached to the final response.

        Args:
            prompt: Input prompt string or message list.
            model: Model identifier (uses instance default if empty).
            **params: Additional parameters (tools, temperature, max_output_tokens).

        Yields:
            LLMResponse with partial text (delta per chunk).
        """
        from google.genai import types

        client = self._get_client()
        model = model or self.model
        tools_param = params.pop("tools", None)
        temperature = params.pop("temperature", self.temperature)
        max_output_tokens = params.pop("max_output_tokens", self.max_output_tokens)

        # Handle str vs List[Dict]
        if isinstance(prompt, str):
            system_instruction = None
            contents = prompt
        else:
            system_instruction, contents = self._convert_messages(prompt, model=model)

        # Build generation config
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        if system_instruction:
            config.system_instruction = system_instruction

        if tools_param:
            config.tools = self._convert_tools(tools_param)

        # Stream from Gemini API.
        #
        # IMPORTANT: function_call parts can arrive in any chunk — not
        # necessarily the last one — so we must accumulate them across
        # the entire stream. The old code only looked at the final chunk
        # and silently dropped function calls emitted mid-stream, which
        # surfaced as "Model returned no text output" warnings.
        last_chunk = None
        has_text = False
        tool_calls: list[dict[str, Any]] = []
        tool_call_chunks: list[Any] = []  # chunks that held tool calls (for raw_content)
        part_summary: dict[str, Any] | None = None

        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            last_chunk = chunk

            # Extract answer text from parts, filtering out thought parts
            # (Gemini 3+) and function_call parts.
            text = self._extract_text_from_parts(chunk)
            if text:
                has_text = True
                yield LLMResponse(text=text, model=model, tokens_used=0, cost=0.0)

            # Accumulate tool calls as they stream in.
            chunk_calls = self._extract_tool_calls(chunk, id_offset=len(tool_calls))
            if chunk_calls:
                tool_call_chunks.append(chunk)
                tool_calls.extend(chunk_calls)

        # Extract token usage from last chunk
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if last_chunk and hasattr(last_chunk, "usage_metadata") and last_chunk.usage_metadata:
            usage = last_chunk.usage_metadata
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = getattr(usage, "total_token_count", 0) or 0

        cost = self._estimate_cost(model, prompt_tokens, completion_tokens)

        if tool_calls:
            # Yield final response with accumulated tool calls
            # (text="" for tool-only responses).
            final = LLMResponse(
                text="",
                model=model,
                tokens_used=total_tokens,
                cost=cost,
                metadata={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
            final.tool_calls = tool_calls

            # Store raw content for replay. When several function_call parts are
            # split across chunks, merge the original SDK Part objects so Gemini's
            # thought_signature metadata survives the immediate follow-up request.
            raw_content = self._merge_tool_call_raw_content(tool_call_chunks, tool_calls)
            if raw_content is not None:
                final.raw_content = raw_content

            yield final

        elif not has_text:
            # Model produced no text AND no tool calls. Could be:
            #  - Gemini 3 Confidence Dropout (thoughts only, no commit)
            #  - Safety / recitation block
            #  - MAX_TOKENS hit before any visible output
            #  - True empty response
            # Dump part-type counts + finish_reason so the caller can tell
            # which one it was. Without this diagnostic the warning is
            # indistinguishable from "something is broken".
            part_summary = self._describe_response_parts(last_chunk) if last_chunk else None
            logger.warning(
                "Model %s returned no text output "
                "(prompt_tokens=%s, completion_tokens=%s, diagnostics=%s). "
                "This may be a Gemini 3 Confidence Dropout, a safety block, "
                "or a truncated reasoning turn.",
                model,
                prompt_tokens,
                completion_tokens,
                part_summary,
            )
            yield LLMResponse(
                text="",
                model=model,
                tokens_used=total_tokens,
                cost=cost,
                metadata={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "empty_response_diagnostics": part_summary,
                },
            )


# ============================================================================
# TODO: OpenAI LLM Provider
# ============================================================================
# OpenAILLMProvider — planned but not yet implemented.
#
# Will provide:
# - Native OpenAI message format (no conversion needed)
# - Tool schema pass-through (BaseAgent already uses OpenAI format)
# - Tool call response parsing
# - Token usage tracking and cost estimation
#
# Models: gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, o3-mini
# SDK: pip install openai
# Env: OPENAI_API_KEY


# ============================================================================
# TODO: Anthropic LLM Provider
# ============================================================================
# AnthropicLLMProvider — planned but not yet implemented.
#
# Will provide:
# - Message format conversion (OpenAI-style → Anthropic format)
# - Tool schema conversion (OpenAI function format → Anthropic tool format)
# - Tool call response parsing
# - Token usage tracking and cost estimation
#
# Models: claude-sonnet-4-5, claude-haiku-4-5, claude-opus-4-6
# SDK: pip install anthropic
# Env: ANTHROPIC_API_KEY


# ============================================================================
# Registration
# ============================================================================

from openbench.core.registry import LLMProviderRegistry  # noqa: E402

LLMProviderRegistry.register(
    "chat",
    "gemini",
    description="Google Gemini LLM provider via google-genai SDK",
)(GeminiLLMProvider)
