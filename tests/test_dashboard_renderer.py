"""Tests for DashboardRenderer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.dashboard import DashboardRenderer
from openbench.output.generators import DashboardGenerator


class TestDashboardRendererRegistry(unittest.TestCase):
    """Tests for DashboardRenderer registration."""

    def test_renderer_is_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertIn("dashboard:default", plugins)

    def test_create_renderer_from_registry(self):
        renderer = ContentRendererRegistry.create("dashboard", "default")
        self.assertIsInstance(renderer, DashboardRenderer)


class TestDashboardRenderer(unittest.TestCase):
    """Tests for dashboard artifact rendering."""

    def setUp(self):
        self.renderer = DashboardRenderer()

    def test_detects_dashboard_artifact(self):
        self.assertTrue(
            self.renderer.detect(
                {
                    "type": "dashboard",
                    "title": "Sales",
                    "url": "/downloads/sales.html",
                    "name": "sales.html",
                }
            )
        )

    def test_detects_dashboard_view_model_without_url(self):
        self.assertTrue(
            self.renderer.detect(
                {
                    "type": "dashboard",
                    "title": "Sales",
                    "viewModel": {
                        "title": "Sales",
                        "datasets": {"sales": [{"region": "EU", "revenue": 10}]},
                        "kpis": [{"label": "Revenue", "value": 10}],
                        "sections": [{"title": "Revenue", "items": []}],
                    },
                }
            )
        )

    def test_does_not_detect_plain_file_card(self):
        self.assertFalse(
            self.renderer.detect({"name": "sales.html", "url": "/downloads/sales.html"})
        )

    def test_render_dashboard_frame_component(self):
        components = self.renderer.render(
            {
                "type": "dashboard",
                "title": "Sales",
                "url": "/downloads/sales.html",
                "name": "sales.html",
                "summary": "Revenue dashboard",
                "mimeType": "text/html",
                "size": 1024,
            },
            surface_id="s1",
        )

        self.assertEqual(len(components), 1)
        component = components[0]
        self.assertEqual(component.component, "ObDashboardFrame")
        self.assertEqual(component.properties["title"], "Sales")
        self.assertEqual(component.properties["dashboardUrl"], "/downloads/sales.html")
        self.assertEqual(component.properties["fileName"], "sales.html")
        self.assertEqual(component.properties["fileSize"], 1024)
        self.assertEqual(component.properties["render_mode"], "html-fallback")

    def test_render_dashboard_view_model_component_without_url(self):
        view_model = {
            "title": "Sales",
            "description": "Revenue dashboard",
            "datasets": {"sales": [{"region": "EU", "revenue": 10}]},
            "kpis": [{"label": "Revenue", "value": 10}],
            "sections": [
                {
                    "title": "Revenue",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "dataset": "sales",
                            "x": "region",
                            "y": "revenue",
                        }
                    ],
                }
            ],
        }

        components = self.renderer.render(
            {"type": "dashboard", "title": "Sales", "viewModel": view_model},
            surface_id="s1",
        )

        self.assertEqual(len(components), 1)
        component = components[0]
        self.assertEqual(component.component, "ObDashboardFrame")
        self.assertNotIn("dashboardUrl", component.properties)
        self.assertEqual(component.properties["render_mode"], "a2ui")
        self.assertEqual(component.properties["viewModel"], view_model)
        self.assertEqual(component.properties["datasets"], view_model["datasets"])
        self.assertEqual(component.properties["kpis"], view_model["kpis"])
        self.assertEqual(component.properties["sections"], view_model["sections"])

    def test_render_top_level_dashboard_data_without_url(self):
        components = self.renderer.render(
            {
                "type": "dashboard",
                "title": "Sales",
                "datasets": {"sales": [{"region": "EU", "revenue": 10}]},
                "kpis": [{"label": "Revenue", "value": 10}],
                "sections": [{"title": "Revenue", "items": []}],
            },
            surface_id="s1",
        )

        self.assertEqual(len(components), 1)
        component = components[0]
        self.assertEqual(component.component, "ObDashboardFrame")
        self.assertNotIn("dashboardUrl", component.properties)
        self.assertEqual(component.properties["render_mode"], "a2ui")
        self.assertEqual(component.properties["datasets"]["sales"][0]["region"], "EU")
        self.assertEqual(component.properties["kpis"][0]["label"], "Revenue")
        self.assertEqual(component.properties["sections"][0]["title"], "Revenue")


class TestDashboardGeneratorMetadata(unittest.TestCase):
    """Tests for dashboard generator A2UI metadata contract."""

    def test_generated_metadata_contains_view_model_for_a2ui_rendering(self):
        view_model = {
            "title": "Sales Dashboard",
            "description": "Revenue dashboard",
            "datasets": {"sales": [{"region": "EU", "revenue": 10}]},
            "kpis": [{"label": "Revenue", "value": 10}],
            "sections": [{"title": "Revenue", "items": []}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "sales.html"
            output = DashboardGenerator().generate(
                view_model,
                output_path=str(output_path),
                public_url="/downloads/sales.html",
            )

        metadata = output.metadata
        self.assertEqual(metadata["type"], "dashboard")
        self.assertEqual(metadata["render_mode"], "a2ui")
        self.assertEqual(metadata["viewModel"], view_model)
        self.assertEqual(metadata["datasets"], view_model["datasets"])
        self.assertEqual(metadata["kpis"], view_model["kpis"])
        self.assertEqual(metadata["sections"], view_model["sections"])
        self.assertEqual(metadata["dashboardUrl"], "/downloads/sales.html")
        self.assertEqual(metadata["url"], "/downloads/sales.html")
        self.assertTrue(metadata["legacy_html"])

    def test_generated_html_table_accepts_object_column_descriptors(self):
        view_model = {
            "title": "Coffee Dashboard",
            "datasets": {
                "top_days": [
                    {"tanggal": "2026-06-01", "pendapatan": 1250000},
                    {"tanggal": "2026-06-02", "pendapatan": 980000},
                ]
            },
            "sections": [
                {
                    "title": "Tables",
                    "items": [
                        {
                            "type": "table",
                            "title": "5 Hari dengan Pendapatan Tertinggi",
                            "dataset": "top_days",
                            "columns": [
                                {"key": "tanggal", "label": "Tanggal"},
                                {"field": "pendapatan", "header": "Pendapatan"},
                            ],
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "coffee.html"
            DashboardGenerator().generate(
                view_model,
                output_path=str(output_path),
                public_url="/downloads/coffee.html",
            )
            html = output_path.read_text(encoding="utf-8")

        self.assertIn("Tanggal", html)
        self.assertIn("Pendapatan", html)
        self.assertIn("2026-06-01", html)
        self.assertIn("1,250,000", html)
        self.assertNotIn("[object Object]", html)


if __name__ == "__main__":
    unittest.main()
