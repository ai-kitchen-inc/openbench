"""Per-user dashboard spec store for Dashboard Chat.

One dashboard per user, persisted as ``dashboards/{username}.json``
under the storage root. The spec is declarative: panels carry a SQL
SELECT plus presentation hints — never data. Chart rows are fetched at
render time through the guarded ``/dashboard/panels/{id}/data`` route.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

PANEL_TYPES = ("kpi", "bar", "line", "area", "pie", "table")
PANEL_WIDTHS = ("third", "half", "twothirds", "full")
PANEL_FORMATS = ("number", "currency", "percent")

_PANEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MAX_PANELS = 24


def _normalize_panel(panel: dict) -> dict:
    """Canonicalize LLM output variance so the frontend contract holds.

    The model occasionally writes ``y`` as a bare string, invents format
    strings like ``"0.0"``, or omits ``width``. Coerce instead of reject —
    these are presentational fields, not correctness issues.
    """
    normalized = dict(panel)
    y = normalized.get("y")
    if isinstance(y, str):
        normalized["y"] = [y]
    elif y is not None and not isinstance(y, list):
        normalized.pop("y", None)
    if normalized.get("format") not in PANEL_FORMATS:
        normalized.pop("format", None)
    normalized.setdefault("width", "half")
    return normalized


def normalize_spec(spec: dict) -> dict:
    """Return a copy of ``spec`` with every panel canonicalized."""
    if not isinstance(spec, dict):
        return spec
    normalized = dict(spec)
    panels = normalized.get("panels")
    if isinstance(panels, list):
        normalized["panels"] = [
            _normalize_panel(panel) if isinstance(panel, dict) else panel for panel in panels
        ]
    return normalized


def validate_spec(spec: dict) -> list[str]:
    """Structural validation; returns a list of human-readable errors."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["Spec must be a JSON object."]
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("Spec needs a non-empty 'title' string.")
    panels = spec.get("panels")
    if not isinstance(panels, list) or not panels:
        return [*errors, "Spec needs a non-empty 'panels' array."]
    if len(panels) > _MAX_PANELS:
        errors.append(f"Too many panels ({len(panels)}); maximum is {_MAX_PANELS}.")
    seen_ids: set[str] = set()
    for index, panel in enumerate(panels):
        label = f"panels[{index}]"
        if not isinstance(panel, dict):
            errors.append(f"{label} must be an object.")
            continue
        panel_id = panel.get("id")
        if not isinstance(panel_id, str) or not _PANEL_ID_RE.match(panel_id):
            errors.append(
                f"{label}: 'id' must be 1-64 chars of lowercase letters, digits, '.', '_', '-'."
            )
        elif panel_id in seen_ids:
            errors.append(f"{label}: duplicate panel id '{panel_id}'.")
        else:
            seen_ids.add(panel_id)
        if panel.get("type") not in PANEL_TYPES:
            errors.append(f"{label}: 'type' must be one of {', '.join(PANEL_TYPES)}.")
        if not isinstance(panel.get("title"), str) or not panel.get("title", "").strip():
            errors.append(f"{label}: needs a non-empty 'title'.")
        if not isinstance(panel.get("sql"), str) or not panel.get("sql", "").strip():
            errors.append(f"{label}: needs a non-empty 'sql' SELECT statement.")
        width = panel.get("width", "half")
        if width not in PANEL_WIDTHS:
            errors.append(f"{label}: 'width' must be one of {', '.join(PANEL_WIDTHS)}.")
    return errors


class DashboardStore:
    """File-backed dashboard specs, one JSON file per user."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()

    def _path_for(self, username: str) -> Path:
        normalized = (username or "").strip().lower()
        # Usernames are validated at registration, but never trust a path join.
        if not re.match(r"^[a-z0-9._-]{1,32}$", normalized):
            raise ValueError(f"Invalid username: {username!r}")
        return self._root / f"{normalized}.json"

    def get(self, username: str) -> dict | None:
        try:
            return json.loads(self._path_for(username).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, username: str, spec: dict) -> dict:
        """Normalize, validate, stamp version/updatedAt, persist atomically."""
        spec = normalize_spec(spec)
        errors = validate_spec(spec)
        if errors:
            raise ValueError("; ".join(errors))
        with self._lock:
            current = self.get(username)
            stamped = dict(spec)
            stamped["version"] = int((current or {}).get("version", 0)) + 1
            stamped["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            path = self._path_for(username)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
            tmp_path.write_text(json.dumps(stamped, indent=2), encoding="utf-8")
            os.replace(tmp_path, path)
        return stamped

    def delete(self, username: str) -> None:
        with contextlib.suppress(OSError):
            self._path_for(username).unlink()


def build_dashboard_store(storage_root: Path) -> DashboardStore:
    return DashboardStore(storage_root / "dashboards")
