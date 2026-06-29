"""Concrete LLM provider implementations.

Provides the concrete LLMProvider that BaseAgent needs to run its reasoning
loop via ProviderService.resolve() -> LLMProviderRegistry.create().

This package was split out of the former flat ``llm_providers.py`` module:
``gemini.py`` holds the provider, ``_tools.py`` / ``_responses.py`` hold its
conversion mixins, and ``costs.py`` holds pricing. New providers (OpenAI,
Anthropic, ...) should each get their own module here and register below.

The Gemini provider is auto-registered on import (see the registration call at
the bottom), so simply importing this package makes ("chat", "gemini")
resolvable.
"""

from __future__ import annotations

from openbench.intelligence.llm_providers.gemini import (
    GeminiLLMProvider,
    _memory_validator_enabled,  # noqa: F401  # re-exported for tests/back-compat
)

__all__ = ["GeminiLLMProvider"]

# ============================================================================
# Registration -- must run on import of openbench.intelligence.llm_providers so
# ProviderService.resolve("chat", "gemini") works without an explicit import of
# the gemini submodule.
# ============================================================================
from openbench.core.registry import LLMProviderRegistry

LLMProviderRegistry.register(
    "chat",
    "gemini",
    description="Google Gemini LLM provider via google-genai SDK",
)(GeminiLLMProvider)
