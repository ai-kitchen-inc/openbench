"""Admin-managed runtime model selections.

Mirrors the capabilities pattern: a small resolved dict persisted in the
settings store under ``"runtime_models"``, merged over code defaults so
adding a field never requires a data migration, with an in-memory cache
the server reads without hitting the store.

Fields:

* ``llm_model`` — the chat model. Applied to agent construction (the
  admin PUT triggers an agent rebuild once wired).
* ``vlm_model`` — the vision model. Stored only for now; the agent keeps
  reading its env configuration.
* ``vector_store`` — ``postgres`` or ``pinecone``. Stored only; store
  wiring is still decided by the database URL.
"""

from __future__ import annotations

import os
from typing import Any

SETTINGS_KEY = "runtime_models"

DEFAULT_LLM_MODEL = "gemini-3.5-flash"

#: Chat models offered in the admin dropdown. Matches the repo's minimum
#: 2.5-series guidance; the env-configured model is appended at runtime
#: when it is not in this list so the active value is always selectable.
LLM_MODEL_OPTIONS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
)

VECTOR_STORE_OPTIONS: tuple[str, ...] = ("postgres", "pinecone")


def _default_vlm_model() -> str:
    # Late import: agent.py pulls in the whole SDK, which this module
    # must not require at import time (tests import it standalone).
    from general_chat.agent import _resolve_vlm_selection

    _provider, model, _requested = _resolve_vlm_selection()
    return model


def _vlm_model_options() -> list[str]:
    from general_chat.agent import _VLM_MODEL_ALIASES

    return sorted({model for _provider, model in _VLM_MODEL_ALIASES.values()})


def default_runtime_settings() -> dict[str, str]:
    """The fully-resolved defaults, honoring the env configuration."""
    return {
        "llm_model": os.getenv("GENERAL_CHAT_MODEL", DEFAULT_LLM_MODEL) or DEFAULT_LLM_MODEL,
        "vlm_model": _default_vlm_model(),
        "vector_store": "postgres",
    }


def runtime_settings_options() -> dict[str, list[str]]:
    """Dropdown options per field, always containing the default value."""
    defaults = default_runtime_settings()
    llm = list(LLM_MODEL_OPTIONS)
    if defaults["llm_model"] not in llm:
        llm.insert(0, defaults["llm_model"])
    vlm = _vlm_model_options()
    if defaults["vlm_model"] not in vlm:
        vlm.insert(0, defaults["vlm_model"])
    return {
        "llm_model": llm,
        "vlm_model": vlm,
        "vector_store": list(VECTOR_STORE_OPTIONS),
    }


def resolve_runtime_settings(stored: Any) -> dict[str, str]:
    """Merge a stored (possibly partial/stale) value over the defaults.

    Unknown keys are dropped and values no longer present in the option
    lists fall back to defaults, so an option list change never leaves a
    dangling selection.
    """
    resolved = default_runtime_settings()
    if not isinstance(stored, dict):
        return resolved
    options = runtime_settings_options()
    for key in resolved:
        value = stored.get(key)
        if isinstance(value, str) and value in options[key]:
            resolved[key] = value
    return resolved


def invalid_runtime_values(partial: Any) -> dict[str, Any]:
    """Known keys in ``partial`` whose value is not a valid option."""
    if not isinstance(partial, dict):
        return {}
    options = runtime_settings_options()
    return {
        key: value
        for key, value in partial.items()
        if key in options and (not isinstance(value, str) or value not in options[key])
    }


class RuntimeSettingsCache:
    """In-memory resolved model selections, backed by the settings store.

    Same contract as ``CapabilityCache``: reads go through ``.value``,
    admin saves go through :meth:`update`, which persists and atomically
    swaps the resolved dict. Single-process uvicorn makes this safe.
    """

    def __init__(self, settings_store: Any):
        self._store = settings_store
        self.value: dict[str, str] = resolve_runtime_settings(settings_store.get(SETTINGS_KEY))

    def update(self, partial: Any, *, updated_by: str = "") -> dict[str, str]:
        """Overlay a (possibly partial) payload, persist, and swap."""
        overlay = dict(self.value)
        if isinstance(partial, dict):
            overlay.update({k: v for k, v in partial.items() if isinstance(v, str)})
        merged = resolve_runtime_settings(overlay)
        self._store.set(SETTINGS_KEY, merged, updated_by=updated_by)
        self.value = merged
        return merged
