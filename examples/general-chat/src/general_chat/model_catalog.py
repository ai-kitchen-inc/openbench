"""Admin-editable model catalog (chat + embedding models).

Mirrors the pricing pattern: a resolved dict persisted in the settings
store under ``"model_catalog"``, merged over code defaults, with an
in-memory cache. The chat-model list feeds the runtime-settings dropdown
via :func:`general_chat.runtime_settings.set_model_options_provider`, so
adding/removing a model here immediately changes what admins and agent
profiles may select — replacing the previously hard-coded tuple.
"""

from __future__ import annotations

from typing import Any

SETTINGS_KEY = "model_catalog"

#: pgvector HNSW indexes reject vectors above 2000 dimensions.
MAX_EMBEDDING_DIMENSION = 2000

EMBEDDING_PROVIDERS: tuple[str, ...] = ("google", "openai")


def _seed_chat_models() -> list[dict[str, str]]:
    from general_chat.runtime_settings import LLM_MODEL_OPTIONS, default_runtime_settings

    models = [{"id": model, "label": model} for model in LLM_MODEL_OPTIONS]
    default = default_runtime_settings()["llm_model"]
    if default not in {entry["id"] for entry in models}:
        models.insert(0, {"id": default, "label": default})
    return models


def _seed_embedding_models() -> list[dict[str, Any]]:
    from general_chat.source_index import (
        DEFAULT_EMBEDDING_DIM,
        DEFAULT_EMBEDDING_MODEL,
        DEFAULT_EMBEDDING_PROVIDER,
    )

    return [
        {
            "id": DEFAULT_EMBEDDING_MODEL,
            "provider": DEFAULT_EMBEDDING_PROVIDER,
            "dimension": DEFAULT_EMBEDDING_DIM,
            "label": DEFAULT_EMBEDDING_MODEL,
        }
    ]


def default_model_catalog() -> dict[str, Any]:
    return {"chatModels": _seed_chat_models(), "embeddingModels": _seed_embedding_models()}


def _clean_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _valid_dimension(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= MAX_EMBEDDING_DIMENSION
    )


def resolve_model_catalog(stored: Any) -> dict[str, Any]:
    """Sanitize a stored (possibly partial/malformed) catalog.

    Malformed entries and duplicate ids are dropped; an empty chat-model
    list falls back to the seed so the dropdown never goes blank.
    """
    resolved = default_model_catalog()
    if not isinstance(stored, dict):
        return resolved

    chat_models: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in stored.get("chatModels") or []:
        if not isinstance(entry, dict):
            continue
        model_id = _clean_id(entry.get("id"))
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        chat_models.append({"id": model_id, "label": _clean_id(entry.get("label")) or model_id})
    if chat_models:
        resolved["chatModels"] = chat_models

    if isinstance(stored.get("embeddingModels"), list):
        embedding_models: list[dict[str, Any]] = []
        seen = set()
        for entry in stored.get("embeddingModels") or []:
            if not isinstance(entry, dict):
                continue
            model_id = _clean_id(entry.get("id"))
            provider = _clean_id(entry.get("provider"))
            if not model_id or model_id in seen or provider not in EMBEDDING_PROVIDERS:
                continue
            if not _valid_dimension(entry.get("dimension")):
                continue
            seen.add(model_id)
            embedding_models.append(
                {
                    "id": model_id,
                    "provider": provider,
                    "dimension": entry["dimension"],
                    "label": _clean_id(entry.get("label")) or model_id,
                }
            )
        resolved["embeddingModels"] = embedding_models

    return resolved


def invalid_catalog_values(partial: Any) -> dict[str, Any]:
    """Entries in ``partial`` that resolve would silently drop — for 400s."""
    if not isinstance(partial, dict):
        return {"payload": partial}
    invalid: dict[str, Any] = {}
    if "chatModels" in partial:
        entries = partial["chatModels"]
        if not isinstance(entries, list):
            invalid["chatModels"] = entries
        else:
            seen: set[str] = set()
            for index, entry in enumerate(entries):
                model_id = _clean_id(entry.get("id")) if isinstance(entry, dict) else ""
                if not model_id or model_id in seen:
                    invalid[f"chatModels[{index}]"] = entry
                seen.add(model_id)
    if "embeddingModels" in partial:
        entries = partial["embeddingModels"]
        if not isinstance(entries, list):
            invalid["embeddingModels"] = entries
        else:
            seen = set()
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    invalid[f"embeddingModels[{index}]"] = entry
                    continue
                model_id = _clean_id(entry.get("id"))
                provider = _clean_id(entry.get("provider"))
                if (
                    not model_id
                    or model_id in seen
                    or provider not in EMBEDDING_PROVIDERS
                    or not _valid_dimension(entry.get("dimension"))
                ):
                    invalid[f"embeddingModels[{index}]"] = entry
                seen.add(model_id)
    return invalid


class ModelCatalogCache:
    """In-memory resolved catalog, backed by the settings store."""

    def __init__(self, settings_store: Any):
        self._store = settings_store
        self.value: dict[str, Any] = resolve_model_catalog(settings_store.get(SETTINGS_KEY))

    def chat_model_ids(self) -> list[str]:
        return [entry["id"] for entry in self.value["chatModels"]]

    def embedding_model(self, model_id: str) -> dict[str, Any] | None:
        for entry in self.value["embeddingModels"]:
            if entry["id"] == model_id:
                return dict(entry)
        return None

    def update(self, partial: Any, *, updated_by: str = "") -> dict[str, Any]:
        """Replace the lists present in ``partial``, persist, and swap."""
        overlay = {
            "chatModels": list(self.value["chatModels"]),
            "embeddingModels": list(self.value["embeddingModels"]),
        }
        if isinstance(partial, dict):
            for key in ("chatModels", "embeddingModels"):
                if isinstance(partial.get(key), list):
                    overlay[key] = partial[key]
        merged = resolve_model_catalog(overlay)
        self._store.set(SETTINGS_KEY, merged, updated_by=updated_by)
        self.value = merged
        return merged
