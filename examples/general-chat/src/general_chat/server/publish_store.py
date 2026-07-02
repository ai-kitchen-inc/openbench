"""Durable store for published dashboards.

A published dashboard is persisted as two files under ``<root>/published/``:

- ``{id}.json`` — the raw ViewModel (re-render / debugging).
- ``{id}.html`` — a self-contained render produced by ``DashboardGenerator``.

The HTML is fully standalone (embedded CSS + JSON + SVG, no JS deps), so the
public ``GET /d/{id}`` route can serve it to anyone without authentication.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from openbench.output.generators.dashboard import DashboardGenerator

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class PublishStore:
    """Persist and load published dashboard artifacts."""

    def __init__(self, root: str | Path) -> None:
        self._dir = Path(root) / "published"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._generator = DashboardGenerator()

    def save(self, view_model: dict[str, Any]) -> str:
        """Persist a ViewModel and its standalone HTML render.

        Args:
            view_model: The dashboard ViewModel to publish.

        Returns:
            The generated publish id (12 hex chars).
        """
        dashboard_id = uuid.uuid4().hex[:12]
        json_path = self._dir / f"{dashboard_id}.json"
        html_path = self._dir / f"{dashboard_id}.html"
        json_path.write_text(
            json.dumps(view_model, ensure_ascii=False, default=str), encoding="utf-8"
        )
        self._generator.generate(content=view_model, output_path=str(html_path))
        return dashboard_id

    def load_html_path(self, dashboard_id: str) -> Path | None:
        """Return the HTML path for a published id, or None if absent/invalid.

        Rejects ids that are not exactly 12 hex chars to prevent path traversal.
        """
        if not isinstance(dashboard_id, str) or not _ID_RE.match(dashboard_id):
            return None
        html_path = self._dir / f"{dashboard_id}.html"
        return html_path if html_path.is_file() else None
