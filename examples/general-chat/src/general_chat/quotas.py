"""Admin-managed monthly token quotas (warn-only).

Mirrors the runtime-settings pattern. Quotas never block a request —
crossing the limit only raises the ``warning`` flag that the usage
endpoints expose. Per-user overrides live in a per-email map inside the
settings value, so no user-table migration is needed.
"""

from __future__ import annotations

from typing import Any

SETTINGS_KEY = "quotas"


def default_quotas() -> dict[str, Any]:
    return {"default_monthly_tokens": 0, "overrides": {}}


def _valid_limit(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def resolve_quotas(stored: Any) -> dict[str, Any]:
    resolved = default_quotas()
    if not isinstance(stored, dict):
        return resolved
    if _valid_limit(stored.get("default_monthly_tokens")):
        resolved["default_monthly_tokens"] = stored["default_monthly_tokens"]
    overrides = stored.get("overrides")
    if isinstance(overrides, dict):
        resolved["overrides"] = {
            str(email).strip().lower(): limit
            for email, limit in overrides.items()
            if str(email).strip() and _valid_limit(limit)
        }
    return resolved


def invalid_quota_values(partial: Any) -> dict[str, Any]:
    if not isinstance(partial, dict):
        return {}
    invalid: dict[str, Any] = {}
    if "default_monthly_tokens" in partial and not _valid_limit(
        partial["default_monthly_tokens"]
    ):
        invalid["default_monthly_tokens"] = partial["default_monthly_tokens"]
    overrides = partial.get("overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            invalid["overrides"] = overrides
        else:
            for email, limit in overrides.items():
                if not _valid_limit(limit):
                    invalid[f"overrides.{email}"] = limit
    return invalid


class QuotaCache:
    """In-memory resolved quotas, backed by the settings store."""

    def __init__(self, settings_store: Any):
        self._store = settings_store
        self.value: dict[str, Any] = resolve_quotas(settings_store.get(SETTINGS_KEY))

    def update(self, partial: Any, *, updated_by: str = "") -> dict[str, Any]:
        overlay = {
            "default_monthly_tokens": self.value["default_monthly_tokens"],
            "overrides": dict(self.value["overrides"]),
        }
        if isinstance(partial, dict):
            if "default_monthly_tokens" in partial:
                overlay["default_monthly_tokens"] = partial["default_monthly_tokens"]
            if isinstance(partial.get("overrides"), dict):
                # Full replacement of the overrides map — the admin UI
                # always sends the complete map, so removals work.
                overlay["overrides"] = partial["overrides"]
        merged = resolve_quotas(overlay)
        self._store.set(SETTINGS_KEY, merged, updated_by=updated_by)
        self.value = merged
        return merged

    def quota_for(self, email: str) -> int:
        """Monthly token limit for ``email``; 0 means unlimited."""
        normalized = (email or "").strip().lower()
        override = self.value["overrides"].get(normalized)
        if override is not None:
            return int(override)
        return int(self.value["default_monthly_tokens"])


def quota_status(limit: int, used: int) -> dict[str, Any]:
    """The warn-only quota payload shared by the usage endpoints."""
    warning = limit > 0 and used >= limit
    percent = round(min(100.0, used * 100.0 / limit), 1) if limit > 0 else 0.0
    return {"limit": limit, "used": used, "warning": warning, "percent": percent}
