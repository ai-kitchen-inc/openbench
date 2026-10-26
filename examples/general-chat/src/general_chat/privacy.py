"""Admin-managed privacy settings.

Mirrors the runtime-settings pattern: a small resolved dict persisted in
the settings store under ``"privacy"``, merged over code defaults so
adding a field never requires a data migration, with an in-memory cache
the server reads without hitting the store.

Fields:

* ``retention_days`` — sessions (and their sources, uploads, index
  artifacts, and LLM memory rows) older than this many days are deleted
  by the retention sweep. ``0`` disables the sweep.
* ``pii_redaction`` — when enabled, user-supplied text is passed through
  :func:`general_chat.pii.redact_pii` before it reaches the LLM.
"""

from __future__ import annotations

from typing import Any

SETTINGS_KEY = "privacy"

#: Retention values above this are treated as configuration mistakes.
MAX_RETENTION_DAYS = 3650


def default_privacy_settings() -> dict[str, Any]:
    return {"retention_days": 0, "pii_redaction": False}


def resolve_privacy_settings(stored: Any) -> dict[str, Any]:
    """Merge a stored (possibly partial/stale) value over the defaults."""
    resolved = default_privacy_settings()
    if not isinstance(stored, dict):
        return resolved
    days = stored.get("retention_days")
    if isinstance(days, int) and not isinstance(days, bool) and 0 <= days <= MAX_RETENTION_DAYS:
        resolved["retention_days"] = days
    redaction = stored.get("pii_redaction")
    if isinstance(redaction, bool):
        resolved["pii_redaction"] = redaction
    return resolved


def invalid_privacy_values(partial: Any) -> dict[str, Any]:
    """Known keys in ``partial`` whose value is out of range or mistyped."""
    if not isinstance(partial, dict):
        return {}
    invalid: dict[str, Any] = {}
    if "retention_days" in partial:
        days = partial["retention_days"]
        if (
            not isinstance(days, int)
            or isinstance(days, bool)
            or not 0 <= days <= MAX_RETENTION_DAYS
        ):
            invalid["retention_days"] = days
    if "pii_redaction" in partial and not isinstance(partial["pii_redaction"], bool):
        invalid["pii_redaction"] = partial["pii_redaction"]
    return invalid


class PrivacySettingsCache:
    """In-memory resolved privacy settings, backed by the settings store.

    Same contract as ``RuntimeSettingsCache``: reads go through
    ``.value``, admin saves go through :meth:`update`, which persists and
    atomically swaps the resolved dict.
    """

    def __init__(self, settings_store: Any):
        self._store = settings_store
        self.value: dict[str, Any] = resolve_privacy_settings(settings_store.get(SETTINGS_KEY))

    def update(self, partial: Any, *, updated_by: str = "") -> dict[str, Any]:
        overlay = dict(self.value)
        if isinstance(partial, dict):
            overlay.update({k: v for k, v in partial.items() if k in overlay})
        merged = resolve_privacy_settings(overlay)
        self._store.set(SETTINGS_KEY, merged, updated_by=updated_by)
        self.value = merged
        return merged
