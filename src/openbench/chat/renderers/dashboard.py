"""Dashboard artifact renderer.

Converts dashboard artifact metadata into A2UI ObDashboardFrame components.
"""

from __future__ import annotations

import logging
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id

logger = logging.getLogger(__name__)


@ContentRendererRegistry.register("dashboard", "default", description="Dashboard artifact renderer")
class DashboardRenderer(ContentRenderer):
    """Renders dashboard artifact metadata to ObDashboardFrame components.

    Expected input format:
        {
            "type": "dashboard",
            "title": "Sales Dashboard",
            "viewModel": {
                "title": "Sales Dashboard",
                "datasets": {"sales_by_region": [...]},
                "kpis": [...],
                "sections": [...],
            },
            "url": "/downloads/sales.html",  # optional legacy/export fallback
        }
    """

    @property
    def content_type(self) -> str:
        return "dashboard"

    def detect(self, content: Any) -> bool:
        """Detect dashboard artifact metadata."""
        if not isinstance(content, dict):
            return False
        if content.get("type") != "dashboard":
            return False
        return bool(
            content.get("url")
            or content.get("dashboardUrl")
            or content.get("viewModel")
            or content.get("view_model")
            or content.get("datasets")
            or content.get("kpis")
            or content.get("sections")
            or content.get("items")
            or content.get("panels")
            or content.get("charts")
            or content.get("widgets")
        )

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert dashboard metadata to an ObDashboardFrame component."""
        if not isinstance(content, dict):
            return []

        url = content.get("dashboardUrl") or content.get("url")
        view_model = content.get("viewModel") or content.get("view_model")
        has_native_props = any(
            key in content
            for key in ("datasets", "kpis", "sections", "items", "panels", "charts", "widgets")
        )
        has_view_model = isinstance(view_model, dict)
        has_dashboard_url = isinstance(url, str) and bool(url)
        render_mode = str(
            content.get("render_mode")
            or content.get("renderMode")
            or ("a2ui" if has_view_model or has_native_props else "html-fallback")
        )
        logger.info(
            "[dashboard] render_mode=%s has_view_model=%s has_dashboard_url=%s title=%s",
            content.get("render_mode") or content.get("renderMode") or render_mode,
            bool(content.get("viewModel") or content.get("view_model")),
            bool(content.get("dashboardUrl") or content.get("url")),
            content.get("title"),
        )
        if not has_dashboard_url and not has_view_model and not has_native_props:
            return []

        props: dict[str, Any] = {
            "title": str(content.get("title") or content.get("name") or "Dashboard"),
            "fileName": str(content.get("name") or content.get("fileName") or "dashboard.html"),
            "mimeType": str(content.get("mimeType") or "text/html"),
            "preview": bool(content.get("preview", True)),
            "height": int(content.get("height") or 420),
            "render_mode": render_mode,
            "renderMode": render_mode,
        }

        if has_dashboard_url:
            props["dashboardUrl"] = url
        if has_view_model:
            props["viewModel"] = view_model
            if "description" in view_model and "description" not in content:
                props["description"] = view_model["description"]
            if "datasets" in view_model and "datasets" not in content:
                props["datasets"] = view_model["datasets"]
            if "kpis" in view_model and "kpis" not in content:
                props["kpis"] = view_model["kpis"]
            if "sections" in view_model and "sections" not in content:
                props["sections"] = view_model["sections"]
        elif content.get("view_model") is not None:
            props["viewModel"] = content["view_model"]

        if "description" in content:
            props["description"] = content["description"]
        if "datasets" in content:
            props["datasets"] = content["datasets"]
        if "kpis" in content:
            props["kpis"] = content["kpis"]
        if "sections" in content:
            props["sections"] = content["sections"]
        for key in ("items", "panels", "charts", "widgets"):
            if key in content:
                props[key] = content[key]
        if content.get("summary"):
            props["summary"] = str(content["summary"])
        if "size" in content:
            props["fileSize"] = content["size"]
        if "path" in content:
            props["path"] = str(content["path"])

        return [
            A2UIComponent(
                id=gen_id("dashboard"),
                component="ObDashboardFrame",
                properties=props,
            )
        ]
