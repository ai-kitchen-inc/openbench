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
import os
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from openbench.core.abstractions import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

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

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple:
        """Convert OpenAI-style messages to Gemini format.

        BaseAgent sends messages as:
            [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]

        Gemini expects:
            system_instruction (str) + contents (list of Content objects)

        Args:
            messages: OpenAI-style message list from AgentMemory.

        Returns:
            Tuple of (system_instruction, contents) for Gemini API.
        """
        from google.genai import types

        system_instruction = None
        contents = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "system":
                system_instruction = content

            elif role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=content)],
                    )
                )

            elif role == "assistant":
                # Use raw content if available (preserves thought_signature)
                raw_content = msg.get("raw_content")
                if raw_content is not None:
                    contents.append(raw_content)
                    continue

                # Reconstruct from extracted data (fallback)
                parts = []
                if content:
                    parts.append(types.Part.from_text(text=content))

                # Handle tool_calls from assistant message
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        name = tc["function"]["name"] if "function" in tc else tc.get("name", "")
                        args = (
                            tc["function"]["arguments"]
                            if "function" in tc
                            else tc.get("arguments", {})
                        )
                        # Parse JSON string arguments if needed
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, TypeError):
                                args = {"raw": args}

                        parts.append(
                            types.Part.from_function_call(
                                name=name,
                                args=args,
                            )
                        )

                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            elif role == "tool":
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
            declarations.append(
                types.FunctionDeclaration(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters=func.get("parameters"),
                )
            )

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
                        "arguments": dict(fc.args) if fc.args else {},
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
        max_retries: int = 3,
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
            system_instruction, contents = self._convert_messages(prompt)

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
            system_instruction, contents = self._convert_messages(prompt)

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
        tool_call_chunk: Any = None  # chunk that held the first tool call (for raw_content)
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
                if tool_call_chunk is None:
                    tool_call_chunk = chunk
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

            # Store raw content for replay. Prefer the chunk that actually
            # carried the function_call parts (preserves thought_signature
            # + function_call together for Gemini 2.5+/3 replay); fall
            # back to the last chunk if we lost track.
            source = tool_call_chunk or last_chunk
            if source and hasattr(source, "candidates") and source.candidates:
                candidate = source.candidates[0]
                if hasattr(candidate, "content") and candidate.content:
                    final.raw_content = candidate.content

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
