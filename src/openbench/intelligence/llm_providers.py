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

import json
import logging
import os
from typing import Any

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

    def _extract_tool_calls(self, response) -> list[dict[str, Any]]:
        """Extract tool calls from Gemini response.

        Converts Gemini's function_calls to the dict format that
        BaseAgent._parse_tool_calls() expects.

        Args:
            response: Gemini API response object.

        Returns:
            List of tool call dicts with id, name, arguments.
        """
        tool_calls = []
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
                        "id": f"call_{i}",
                        "name": fc.name,
                        "arguments": dict(fc.args) if fc.args else {},
                    }
                )

        return tool_calls

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

        # Call Gemini API
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

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
            try:
                text = response.text
            except Exception:
                # response.text raises if no text parts
                text = ""

        llm_response = LLMResponse(
            text=text,
            model=model,
            tokens_used=total_tokens,
            cost=cost,
            metadata={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
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
