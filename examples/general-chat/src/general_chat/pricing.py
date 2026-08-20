"""Admin-editable per-model pricing table for the cost dashboard.

Mirrors the runtime-settings pattern: a resolved dict persisted in the
settings store, merged over code defaults, with an in-memory cache.

Seeded from the SDK's Gemini list-price table so a fresh deployment
shows sensible costs; the admin edits survive Google repricing without
a redeploy. Usage rows store cost computed from this table at write
time, so a later rate edit never rewrites history.
"""

from __future__ import annotations

from typing import Any

SETTINGS_KEY = "pricing"


def _seed_models() -> dict[str, dict[str, float]]:
    # Read-only import of the SDK's list prices (USD per 1M tokens).
    from openbench.intelligence.llm_providers.costs import _GEMINI_COSTS

    return {
        model: {"input_per_1m": rates["input"], "output_per_1m": rates["output"]}
        for model, rates in _GEMINI_COSTS.items()
    }


def default_pricing() -> dict[str, Any]:
    return {"models": _seed_models()}


def _valid_rate(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def resolve_pricing(stored: Any) -> dict[str, Any]:
    """Merge stored rates over the seed table.

    Unknown models are kept (an admin may add one ahead of the SDK);
    malformed entries fall back to the seed or are dropped.
    """
    resolved = default_pricing()
    if not isinstance(stored, dict):
        return resolved
    models = stored.get("models")
    if not isinstance(models, dict):
        return resolved
    for model, rates in models.items():
        if not isinstance(model, str) or not isinstance(rates, dict):
            continue
        entry = dict(resolved["models"].get(model, {"input_per_1m": 0.0, "output_per_1m": 0.0}))
        if _valid_rate(rates.get("input_per_1m")):
            entry["input_per_1m"] = float(rates["input_per_1m"])
        if _valid_rate(rates.get("output_per_1m")):
            entry["output_per_1m"] = float(rates["output_per_1m"])
        resolved["models"][model] = entry
    return resolved


def invalid_pricing_values(partial: Any) -> dict[str, Any]:
    """Model entries in ``partial`` whose rates are malformed."""
    if not isinstance(partial, dict):
        return {}
    models = partial.get("models")
    if models is None:
        return {}
    if not isinstance(models, dict):
        return {"models": models}
    invalid: dict[str, Any] = {}
    for model, rates in models.items():
        if not isinstance(rates, dict):
            invalid[str(model)] = rates
            continue
        for key in ("input_per_1m", "output_per_1m"):
            if key in rates and not _valid_rate(rates[key]):
                invalid[f"{model}.{key}"] = rates[key]
    return invalid


class PricingCache:
    """In-memory resolved pricing, backed by the settings store."""

    def __init__(self, settings_store: Any):
        self._store = settings_store
        self.value: dict[str, Any] = resolve_pricing(settings_store.get(SETTINGS_KEY))
        self._warned_models: set[str] = set()

    def update(self, partial: Any, *, updated_by: str = "") -> dict[str, Any]:
        overlay = {"models": dict(self.value["models"])}
        if isinstance(partial, dict) and isinstance(partial.get("models"), dict):
            for model, rates in partial["models"].items():
                if isinstance(rates, dict):
                    current = dict(overlay["models"].get(model, {}))
                    current.update(rates)
                    overlay["models"][model] = current
        merged = resolve_pricing(overlay)
        self._store.set(SETTINGS_KEY, merged, updated_by=updated_by)
        self.value = merged
        return merged

    def compute_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """USD cost for one call at the current rates; unknown model → 0.0."""
        rates = self.value["models"].get(model)
        if rates is None:
            if model and model not in self._warned_models:
                self._warned_models.add(model)
                import logging

                logging.getLogger(__name__).warning(
                    "No pricing entry for model %r — costing it at 0", model
                )
            return 0.0
        return (
            prompt_tokens * rates["input_per_1m"] + completion_tokens * rates["output_per_1m"]
        ) / 1_000_000
