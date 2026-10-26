"""Per-call LLM usage capture.

``_MeteringLLMProvider`` mirrors the handler's ``_DebugLLMProvider``
shape: a thin wrapper installed on the per-request agent copy, so it
sees every LLM call — all tool-loop iterations and the session-title
generation — not just the aggregated turn.

``UsageRecorder`` turns captured token counts into stored rows. Cost is
computed from the admin-editable pricing table at write time, and the
provider's own ``resp.cost`` is deliberately ignored — the admin's
rates must win, and stored history must not change when rates do.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from openbench.core.abstractions import LLMProvider, LLMResponse

from general_chat.usage_store import UsageRecord

logger = logging.getLogger(__name__)


class UsageRecorder:
    """Append usage rows; a metering failure must never kill a turn."""

    def __init__(self, usage_store: Any, pricing_cache: Any):
        self._store = usage_store
        self._pricing = pricing_cache

    def record(
        self,
        *,
        owner: str,
        session_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        try:
            cost = self._pricing.compute_cost(model, prompt_tokens, completion_tokens)
            self._store.append(
                UsageRecord(
                    owner=owner,
                    session_id=session_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    cost_usd=cost,
                )
            )
        except Exception:
            logger.warning("Usage append failed for owner=%s", owner, exc_info=True)


def _usage_from_response(response: LLMResponse) -> tuple[int, int] | None:
    """Extract (prompt, completion) tokens, or None when the response carries no usage."""
    metadata = getattr(response, "metadata", None) or {}
    prompt_tokens = int(metadata.get("prompt_tokens", 0) or 0)
    completion_tokens = int(metadata.get("completion_tokens", 0) or 0)
    if prompt_tokens or completion_tokens or getattr(response, "tokens_used", 0):
        return prompt_tokens, completion_tokens
    return None


class _MeteringLLMProvider(LLMProvider):
    """Thin provider wrapper that records usage after delegating."""

    def __init__(
        self,
        inner: LLMProvider,
        on_usage: Callable[[str, int, int], None],
    ):
        self._inner = inner
        self._on_usage = on_usage

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _record(self, model: str, response: LLMResponse) -> None:
        usage = _usage_from_response(response)
        if usage is None:
            return
        try:
            self._on_usage(model or getattr(response, "model", ""), usage[0], usage[1])
        except Exception:
            logger.warning("Usage callback failed", exc_info=True)

    def generate(
        self, prompt: str | list[dict[str, Any]], model: str = "", **params
    ) -> LLMResponse:
        response = self._inner.generate(prompt, model, **params)
        self._record(model, response)
        return response

    def generate_stream(self, prompt: str | list[dict[str, Any]], model: str = "", **params):
        for chunk in self._inner.generate_stream(prompt, model, **params):
            # Deltas carry tokens_used=0; only the trailing usage-bearing
            # response (or a tool-call final) records.
            self._record(model, chunk)
            yield chunk
