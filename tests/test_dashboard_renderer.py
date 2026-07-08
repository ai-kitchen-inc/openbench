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

    def test_render_dashboard_passes_template_metadata_to_a2ui(self):
        components = self.renderer.render(
            {
                "type": "dashboard",
                "title": "Sales",
                "viewModel": {"title": "Sales", "kpis": [], "sections": []},
                "customTemplate": {"source": "design.md", "format": "markdown", "chars": 100},
                "templateSource": "user",
                "templateFormat": "markdown",
                "templateName": "design.md",
            },
            surface_id="s1",
        )

        props = components[0].properties
        self.assertEqual(props["customTemplate"]["format"], "markdown")
        self.assertEqual(props["templateSource"], "user")
        self.assertEqual(props["templateFormat"], "markdown")
        self.assertEqual(props["templateName"], "design.md")


class TestDashboardGeneratorMetadata(unittest.TestCase):
    """Tests for dashboard generator A2UI metadata contract."""

    def _generate_dashboard(self, view_model: dict) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "dashboard.html"
            output = DashboardGenerator().generate(view_model, output_path=str(output_path))
            html = output_path.read_text(encoding="utf-8")
        return output.metadata["viewModel"], html

    def _assert_rendered_dashboard(
        self,
        view_model: dict,
        *,
        expect_kpi: bool = True,
        expect_chart: bool = True,
        expect_table: bool = False,
    ) -> dict:
        normalized, html = self._generate_dashboard(view_model)
        if expect_kpi:
            self.assertTrue(normalized["kpis"], "expected normalized KPI cards")
            self.assertIn("ob-kpi", html)
        if expect_chart:
            items = [
                item
                for section in normalized["sections"]
                for item in section.get("items", [])
                if item.get("type") == "chart"
            ]
            self.assertTrue(items, "expected normalized chart items")
            self.assertIn("ob-panel--chart", html)
            self.assertIn("<svg", html)
            self.assertNotIn("No chart data available", html)
        if expect_table:
            self.assertTrue(
                any(
                    item.get("type") == "table"
                    for section in normalized["sections"]
                    for item in section.get("items", [])
                ),
                "expected normalized table items",
            )
            self.assertIn("ob-panel--table", html)
        self.assertNotIn("[object Object]", html)
        self.assertNotIn("{'columns':", html)
        return normalized

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

    def test_generated_html_uses_uploaded_html_template(self):
        view_model = {
            "title": "Template Sales Dashboard",
            "datasets": {"sales": [{"region": "EU", "revenue": 10}]},
            "kpis": [{"label": "Revenue", "value": 10}],
            "sections": [{"title": "Revenue", "items": []}],
        }
        template_path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "general-chat"
            / "template-dashboard-sample"
            / "template.html"
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "templated.html"
            output = DashboardGenerator().generate(
                view_model,
                output_path=str(output_path),
                template_path=str(template_path),
            )
            html = output_path.read_text(encoding="utf-8")

        self.assertEqual(output.metadata["render_mode"], "a2ui")
        self.assertEqual(output.metadata["custom_template"]["format"], "html")
        self.assertEqual(output.metadata["template_source"], "user")
        self.assertEqual(output.metadata["template_format"], "html")
        self.assertIn('data-custom-template="executive-html"', html)
        self.assertIn("Template Sales Dashboard", html)
        self.assertIn("openbench-dashboard-view-model", html)

    def test_uploaded_html_template_without_placeholders_is_hydrated(self):
        view_model = {
            "title": "Coffee Sales Advanced Dashboard",
            "kpis": [
                {"label": "Total Sales", "value": 115431.58},
                {"label": "Total Transactions", "value": 3636},
                {"label": "Avg Transaction", "value": 31.75},
                {"label": "Top Product", "value": "Americano with Milk"},
                {"label": "Peak Hour", "value": "10:00 AM"},
            ],
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Sales by Product",
                            "data": [
                                {"label": "Latte", "sales": 27866.3},
                                {"label": "Americano", "sales": 15062.26},
                            ],
                            "x_field": "label",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "line",
                            "title": "Monthly Sales Trend",
                            "data": [
                                {"label": "Jan", "sales": 6398.86},
                                {"label": "Feb", "sales": 13215.48},
                            ],
                            "x_field": "label",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Sales by Cash Type",
                            "data": [
                                {"label": "Card", "sales": 112245.58},
                                {"label": "Cash", "sales": 3186},
                            ],
                            "x_field": "label",
                            "y_field": "sales",
                        },
                    ],
                }
            ],
        }
        template_path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "general-chat"
            / "template-dashboard-sample"
            / "template - advanced.html"
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "advanced.html"
            DashboardGenerator().generate(
                view_model,
                output_path=str(output_path),
                template_path=str(template_path),
            )
            html = output_path.read_text(encoding="utf-8")

        self.assertIn('<div class="dashboard">', html)
        self.assertIn('data-openbench-filled="kpi"', html)
        self.assertIn('data-openbench-filled="chart"', html)
        self.assertEqual(html.count('data-openbench-filled="chart"'), 4)
        self.assertIn("large-area openbench-template-chart", html)
        self.assertIn("medium-area openbench-template-chart", html)
        self.assertNotIn('<div class="medium-area"></div>', html)
        self.assertNotIn("Insight item", html)
        self.assertNotIn("Footer Panel", html)
        self.assertIn("Sales by Product", html)
        self.assertIn("Monthly Sales Trend", html)
        self.assertIn("115,431.58", html)
        self.assertIn("openbench-dashboard-view-model", html)
        self.assertNotIn('<main class="ob-dashboard"', html)
        self.assertLess(html.index("Sales by Product"), html.index("openbench-dashboard-view-model"))

    def test_generated_html_uses_uploaded_markdown_design_template(self):
        view_model = {
            "title": "Design Brief Dashboard",
            "kpis": [{"label": "Revenue", "value": 10}],
            "sections": [],
        }
        template_path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "general-chat"
            / "template-dashboard-sample"
            / "design.md"
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "design.html"
            output = DashboardGenerator().generate(
                view_model,
                output_path=str(output_path),
                template_path=str(template_path),
            )
            html = output_path.read_text(encoding="utf-8")

        self.assertEqual(output.metadata["custom_template"]["format"], "markdown")
        self.assertEqual(output.metadata["template_source"], "user")
        self.assertEqual(output.metadata["template_format"], "markdown")
        self.assertIn('data-custom-template="markdown-design"', html)
        self.assertIn("Red Markdown Dashboard Design", html)
        self.assertIn("--ob-accent: #b91c1c", html)

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

    def test_dataset_backed_kpis_and_widget_sections_render(self):
        """The LLM dialect: KPI values in a dataset + panels under ``widgets``."""
        view_model = {
            "title": "Coffee Sales Performance Dashboard",
            "datasets": {
                "kpis": [
                    {
                        "total_revenue": 115431.58,
                        "total_transactions": 3636,
                        "avg_transaction_value": 31.7468591859186,
                    }
                ],
                # Measure first, label second — exercises x/y axis inference.
                "weekday_revenue": [
                    {"revenue": 17925.1, "Weekday": "Mon"},
                    {"revenue": 18637.38, "Weekday": "Tue"},
                ],
            },
            "kpis": [
                {
                    "label": "Total Revenue",
                    "dataset_id": "kpis",
                    "value_column": "total_revenue",
                    "format": "$#,###.00",
                },
                {
                    "label": "Total Transactions",
                    "dataset_id": "kpis",
                    "value_column": "total_transactions",
                    "format": "#,###",
                },
            ],
            "sections": [
                {
                    "title": "Sales Trends",
                    "widgets": [
                        {
                            "title": "Revenue by Weekday",
                            "chart_type": "bar",
                            "dataset_id": "weekday_revenue",
                            "x_axis": "Weekday",
                            "y_axis": "revenue",
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "coffee.html"
            DashboardGenerator().generate(view_model, output_path=str(output_path))
            html = output_path.read_text(encoding="utf-8")

        # KPI values resolve from the dataset column + currency format applied.
        self.assertIn("$115,431.58", html)
        self.assertIn("3,636", html)
        # The widget section renders a chart panel (not dropped).
        self.assertIn("Revenue by Weekday", html)
        self.assertIn("ob-panel--chart", html)
        self.assertIn("<svg", html)
        self.assertNotIn("No chart data available.", html)
        # Theme-aware CSS is present for light/dark parity.
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn('data-theme="dark"', html)

    def test_layout_components_dialect_renders_kpis_and_charts(self):
        """The MCP/LLM dialect: panels under top-level ``components``."""
        view_model = {
            "title": "Dashboard Penjualan Kopi",
            "layout": {"columns": 3},
            "datasets": {
                "dataset_1": [{"coffee_name": "Latte", "revenue": 27866.3}],
                "dataset_2": [
                    {"date": "2024-03-01", "daily_revenue": 396.3},
                    {"date": "2024-03-02", "daily_revenue": 228.1},
                ],
            },
            "components": [
                {
                    "id": "kpi_total_sales",
                    "type": "kpi",
                    "content": {
                        "title": "Total Penjualan",
                        "value": 115431.58,
                        "variant": "currency",
                    },
                },
                {
                    "id": "chart_monthly_trend",
                    "type": "chart",
                    "content": {
                        "title": "Tren Penjualan Bulanan",
                        "data": "dataset_2",
                        "type": "line",
                        "x": "date",
                        "y": "daily_revenue",
                    },
                },
                {
                    "id": "chart_payment_method",
                    "type": "chart",
                    "content": {
                        "title": "Penjualan Kopi",
                        "data": "dataset_1",
                        "type": "bar",
                        "x": "coffee_name",
                        "y": "revenue",
                    },
                },
            ],
            "kpis": [],
            "sections": [{"title": "Dashboard", "items": []}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "coffee.html"
            output = DashboardGenerator().generate(view_model, output_path=str(output_path))
            html = output_path.read_text(encoding="utf-8")

        rendered = output.metadata["viewModel"]
        self.assertEqual(rendered["kpis"][0]["label"], "Total Penjualan")
        self.assertEqual(rendered["sections"][0]["items"][0]["chart_type"], "line")
        self.assertIn("Total Penjualan", html)
        self.assertIn("$115,431.58", html)
        self.assertIn("Tren Penjualan Bulanan", html)
        self.assertIn("Penjualan Kopi", html)
        self.assertIn("Latte", html)
        self.assertIn("ob-panel--chart", html)
        self.assertNotIn("No chart data available.", html)

    def test_components_view_data_hydrates_empty_sections(self):
        view_model = {
            "title": "Coffee Sales Dashboard",
            "components": [
                {
                    "component": "kpi_grid",
                    "props": {
                        "items": [
                            {
                                "label": "Total Revenue",
                                "value": 115431.58,
                                "variant": "currency",
                            }
                        ]
                    },
                },
                {
                    "component": "chart",
                    "view_data": [
                        {"coffee_name": "Latte", "revenue": 27866.3},
                        {"coffee_name": "Americano", "revenue": 15062.26},
                    ],
                    "props": {
                        "title": "Revenue by Coffee Product",
                        "chart_type": "bar",
                        "x_field": "coffee_name",
                        "y_field": "revenue",
                    },
                },
                {
                    "component": "chart",
                    "view_data": [
                        {"Time_of_Day": "Night", "revenue": 39033.34},
                        {"Time_of_Day": "Morning", "revenue": 37380.2},
                    ],
                    "props": {
                        "title": "Revenue by Time of Day",
                        "chart_type": "pie",
                        "x_field": "Time_of_Day",
                        "y_field": "revenue",
                    },
                },
            ],
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Revenue by Coffee Product",
                            "data": [],
                            "x_field": "coffee_name",
                            "y_field": "revenue",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Revenue by Time of Day",
                            "data": [],
                            "x_field": "Time_of_Day",
                            "y_field": "revenue",
                        },
                    ],
                }
            ],
        }

        normalized = self._assert_rendered_dashboard(view_model)
        self.assertNotIn("components", normalized)
        charts = normalized["sections"][0]["items"]
        self.assertEqual(charts[0]["data"][0]["coffee_name"], "Latte")
        self.assertEqual(charts[1]["data"][0]["Time_of_Day"], "Night")

    def test_nested_section_components_with_view_model_render(self):
        """The MCP/LLM dialect: top-level components can be section containers."""
        view_model = {
            "title": "Coffee Sales Performance Dashboard",
            "components": [
                {
                    "type": "section",
                    "columns": 4,
                    "components": [
                        {
                            "type": "kpi",
                            "label": "Total Revenue",
                            "value": 115431.58,
                            "value_format": "$,.2f",
                        },
                        {
                            "type": "kpi",
                            "label": "Total Transactions",
                            "value": 3636,
                        },
                    ],
                },
                {
                    "type": "section",
                    "columns": 2,
                    "components": [
                        {
                            "type": "chart",
                            "view_model": {
                                "type": "line_chart",
                                "data": [
                                    {"label": "Jan", "value": 6398.86},
                                    {"label": "Feb", "value": 13215.48},
                                ],
                            },
                            "options": {"title": "Monthly Revenue Trend"},
                        },
                        {
                            "type": "chart",
                            "view_model": {
                                "type": "bar_chart",
                                "data": [
                                    {"label": "Latte", "value": 27866.3},
                                    {"label": "Americano with Milk", "value": 25269.12},
                                ],
                            },
                            "options": {"title": "Revenue by Coffee Type"},
                        },
                    ],
                },
            ],
            "datasets": {},
            "kpis": [],
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "section",
                            "components": [
                                {
                                    "type": "chart",
                                    "view_model": {
                                        "type": "bar_chart",
                                        "data": [{"label": "Latte", "value": 27866.3}],
                                    },
                                    "options": {"title": "Stale Wrapped Section"},
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "coffee.html"
            output = DashboardGenerator().generate(view_model, output_path=str(output_path))
            html = output_path.read_text(encoding="utf-8")

        rendered = output.metadata["viewModel"]
        self.assertEqual(rendered["kpis"][0]["label"], "Total Revenue")
        self.assertEqual(rendered["sections"][0]["items"][0]["chart_type"], "line")
        self.assertIn("Total Revenue", html)
        self.assertIn("$115,431.58", html)
        self.assertIn("Total Transactions", html)
        self.assertIn("3,636", html)
        self.assertIn("Monthly Revenue Trend", html)
        self.assertIn("Revenue by Coffee Type", html)
        self.assertIn("Latte", html)
        self.assertIn("<svg", html)
        self.assertNotIn("<h3>Summary</h3><p></p>", html)
        self.assertNotIn("No chart data available.", html)

    def test_normalizes_canonical_shape_with_table(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Canonical Coffee Dashboard",
                "kpis": [{"label": "Total Revenue", "value": 115431.58, "value_format": "$0,0.00"}],
                "sections": [
                    {
                        "title": "Dashboard",
                        "items": [
                            {
                                "type": "chart",
                                "chart_type": "bar",
                                "title": "Revenue by Product",
                                "data": [
                                    {"product": "Latte", "revenue": 27866.3},
                                    {"product": "Americano", "revenue": 25269.12},
                                ],
                                "x_field": "product",
                                "y_field": "revenue",
                            },
                            {
                                "type": "table",
                                "title": "Top Products",
                                "data": [{"product": "Latte", "revenue": 27866.3}],
                                "columns": ["product", "revenue"],
                            },
                        ],
                    }
                ],
            },
            expect_table=True,
        )

        self.assertEqual(normalized["sections"][0]["items"][0]["x_field"], "product")

    def test_normalizes_top_level_components(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Top Level Components",
                "components": [
                    {"type": "kpi", "title": "Revenue", "value": 123},
                    {
                        "type": "bar_chart",
                        "title": "Revenue by Product",
                        "data": [{"product": "Latte", "revenue": 123}],
                        "x": "product",
                        "y": "revenue",
                    },
                    {
                        "type": "table",
                        "title": "Top Products",
                        "data": [{"product": "Latte", "revenue": 123}],
                        "columns": ["product", "revenue"],
                    },
                ],
            },
            expect_table=True,
        )

        self.assertEqual(normalized["sections"][0]["items"][0]["chart_type"], "bar")

    def test_normalizes_layout_components_with_parameters(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Layout Components",
                "layout": {"columns": 2},
                "components": [
                    {
                        "id": "kpi_total_sales",
                        "type": "kpi",
                        "parameters": {"label": "Total Revenue", "value": 32866573.74},
                    },
                    {
                        "id": "chart_sales",
                        "type": "bar_chart",
                        "parameters": {
                            "title": "Revenue by Type",
                            "data": [{"type": "Latte", "sales": 123}],
                            "x_field": "type",
                            "y_field": "sales",
                        },
                    },
                ],
            }
        )

        self.assertEqual(normalized["kpis"][0]["label"], "Total Revenue")
        self.assertEqual(normalized["sections"][0]["items"][0]["y_field"], "sales")

    def test_normalizes_section_components_with_y_fields(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Section Components",
                "components": [
                    {
                        "type": "section",
                        "columns": 2,
                        "components": [
                            {"type": "kpi", "title": "Revenue", "value": 123},
                            {
                                "type": "bar_chart",
                                "title": "Revenue by Product",
                                "data": [{"product": "Latte", "revenue": 123}],
                                "x_field": "product",
                                "y_fields": ["revenue"],
                            },
                        ],
                    }
                ],
            }
        )

        self.assertEqual(normalized["sections"][0]["items"][0]["y_field"], "revenue")

    def test_normalizes_row_columns_props_with_dataset_axes(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Row Props Dashboard",
                "datasets": {
                    "revenue_trend": [{"month": "2022-01", "revenue": 1419751.89}],
                    "top_products": [{"product": "Latte", "revenue": 27866.3}],
                },
                "components": [
                    {
                        "component": "row",
                        "columns": [
                            {
                                "component": "kpi",
                                "props": {
                                    "label": "Total Revenue",
                                    "value": 32866573.74,
                                    "format": "$0.2s",
                                },
                            },
                            {
                                "component": "chart",
                                "props": {
                                    "title": "Monthly Revenue Trend",
                                    "dataset_id": "revenue_trend",
                                    "chart_type": "line",
                                    "x_axis": {"property": "month", "label": "Month"},
                                    "y_axis": {"property": "revenue", "label": "Revenue"},
                                },
                            },
                            {
                                "component": "table",
                                "props": {
                                    "title": "Top Products",
                                    "dataset_id": "top_products",
                                    "columns": [{"key": "product"}, {"key": "revenue"}],
                                },
                            },
                        ],
                    }
                ],
            },
            expect_table=True,
        )

        chart = normalized["sections"][0]["items"][0]
        self.assertEqual(chart["chart_type"], "line")
        self.assertEqual(chart["x_field"], "month")
        self.assertEqual(chart["y_field"], "revenue")

    def test_normalizes_chartjs_labels_and_datasets(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Chart.js Dashboard",
                "type": "chart",
                "chart_type": "bar",
                "data": {
                    "labels": ["Latte", "Americano"],
                    "datasets": [{"label": "Revenue", "data": [27866.3, 25269.12]}],
                },
            },
            expect_kpi=False,
        )

        chart = normalized["sections"][0]["items"][0]
        self.assertEqual(chart["x_field"], "label")
        self.assertEqual(chart["y_field"], "revenue")
        self.assertEqual(chart["data"][0]["label"], "Latte")

    def test_normalizes_chartjs_labels_and_values(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Chart.js Values Dashboard",
                "charts": [
                    {
                        "title": "Sales by Coffee Type",
                        "type": "pie",
                        "data": {
                            "labels": ["Latte", "Americano"],
                            "values": [27866.3, 25269.12],
                        },
                    }
                ],
            },
            expect_kpi=False,
        )

        chart = normalized["sections"][0]["items"][0]
        self.assertEqual(chart["chart_type"], "pie")
        self.assertEqual(chart["x_field"], "label")
        self.assertEqual(chart["y_field"], "value")
        self.assertEqual(chart["data"][0], {"label": "Latte", "value": 27866.3})

    def test_normalizes_kpi_grid_and_loose_charts_list(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Loose Charts Dashboard",
                "charts": [
                    {
                        "type": "kpi_grid",
                        "data": {"values": [{"label": "Revenue", "value": 123}]},
                    },
                    {
                        "type": "bar",
                        "title": "Revenue by Product",
                        "data": {
                            "labels": ["Latte", "Americano"],
                            "datasets": [{"label": "Revenue", "data": [123, 95]}],
                        },
                    },
                ],
            }
        )

        self.assertEqual(normalized["kpis"][0]["label"], "Revenue")
        self.assertEqual(normalized["sections"][0]["items"][0]["chart_type"], "bar")

    def test_normalizes_chart_data_config_objects(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Coffee Sales Analysis Dashboard",
                "kpis": [{"label": "Total Sales", "value": 115431.58}],
                "sections": [
                    {
                        "title": "Dashboard",
                        "items": [
                            {
                                "type": "chart",
                                "title": "Placeholder Chart",
                                "data": [],
                                "x_field": "name",
                                "y_field": "value",
                            }
                        ],
                    }
                ],
                "charts": [
                    {
                        "data": {"x": "Month_name", "y": "sales", "dataset_id": "monthly_sales"},
                        "type": "line",
                        "title": "Monthly Sales Trend",
                    },
                    {
                        "title": "Sales by Payment Method",
                        "data": {
                            "dataset_id": "cash_type_sales",
                            "value": "sales",
                            "label": "cash_type",
                        },
                        "type": "pie",
                    },
                ],
                "datasets": {
                    "monthly_sales": [
                        {"Month_name": "Jan", "Monthsort": 1, "sales": 6398.86},
                        {"Month_name": "Feb", "Monthsort": 2, "sales": 13215.48},
                    ],
                    "cash_type_sales": [
                        {"cash_type": "card", "sales": 112245.58},
                        {"cash_type": "cash", "sales": 3186.0},
                    ],
                },
            }
        )

        first = normalized["sections"][0]["items"][0]
        self.assertEqual(first["data"][0]["Month_name"], "Jan")
        self.assertEqual(first["x_field"], "Month_name")
        self.assertEqual(first["y_field"], "sales")

    def test_synthesizes_chart_panels_from_datasets_when_items_empty(self):
        normalized = self._assert_rendered_dashboard(
            {
                "title": "Executive Sales Dashboard",
                "datasets": {
                    "kpis": [{"total_revenue": 32866573.74}],
                    "revenue_by_payment": [
                        {"payment_method": "Wallet", "revenue": 6678638.47},
                        {"payment_method": "UPI", "revenue": 6579441.44},
                    ],
                    "revenue_by_month": [
                        {"month": "2022-01", "revenue": 1419751.89},
                        {"month": "2022-02", "revenue": 1266714.29},
                    ],
                },
                "kpis": [{"label": "Total Revenue", "value": 32866573.74, "format": "$0.2s"}],
                "sections": [{"title": "Executive Summary", "items": []}],
            }
        )

        chart_titles = [item["title"] for item in normalized["sections"][0]["items"]]
        self.assertIn("Revenue By Payment", chart_titles)
        self.assertIn("Revenue By Month", chart_titles)


if __name__ == "__main__":
    unittest.main()
