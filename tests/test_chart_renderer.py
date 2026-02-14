"""Tests for ChartRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.chart import ChartRenderer


class TestChartRendererRegistry(unittest.TestCase):
    """Tests for ChartRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("chart" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("chart", "default")
        self.assertIsInstance(renderer, ChartRenderer)


class TestChartRenderer(unittest.TestCase):
    """Tests for ChartRenderer."""

    def setUp(self):
        self.renderer = ChartRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "chart")

    # -- detect --

    def test_detect_bar_chart(self):
        self.assertTrue(self.renderer.detect({"type": "bar", "data": []}))

    def test_detect_line_chart(self):
        self.assertTrue(self.renderer.detect({"type": "line", "data": [1, 2]}))

    def test_detect_pie_chart(self):
        self.assertTrue(self.renderer.detect({"type": "pie", "data": []}))

    def test_detect_scatter_chart(self):
        self.assertTrue(self.renderer.detect({"type": "scatter", "data": []}))

    def test_detect_area_chart(self):
        self.assertTrue(self.renderer.detect({"type": "area", "data": []}))

    def test_detect_invalid_type(self):
        self.assertFalse(self.renderer.detect({"type": "donut", "data": []}))

    def test_detect_missing_data(self):
        self.assertFalse(self.renderer.detect({"type": "bar"}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("bar chart"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    # -- render --

    def test_render_basic_bar_chart(self):
        content = {
            "type": "bar",
            "data": [{"name": "Q1", "value": 100}, {"name": "Q2", "value": 200}],
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        chart = components[0]
        self.assertEqual(chart.component, "ObChart")
        self.assertEqual(chart.properties["chartType"], "bar")
        self.assertEqual(len(chart.properties["data"]), 2)
        self.assertEqual(chart.properties["width"], "100%")
        self.assertEqual(chart.properties["height"], "300px")

    def test_render_with_title(self):
        content = {
            "type": "line",
            "data": [{"x": 1, "y": 2}],
            "title": "Revenue Over Time",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 2)
        # First: title text
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "Revenue Over Time")
        self.assertEqual(components[0].properties["variant"], "h4")
        # Second: chart
        self.assertEqual(components[1].component, "ObChart")
        self.assertEqual(components[1].properties["chartType"], "line")

    def test_render_with_options(self):
        content = {
            "type": "pie",
            "data": [{"name": "A", "value": 50}],
            "options": {"innerRadius": 30},
        }
        components = self.renderer.render(content, surface_id="s1")
        chart = components[0]
        self.assertEqual(chart.properties["options"]["innerRadius"], 30)

    def test_render_custom_dimensions(self):
        content = {
            "type": "area",
            "data": [],
            "width": "500px",
            "height": "400px",
        }
        components = self.renderer.render(content, surface_id="s1")
        chart = components[0]
        self.assertEqual(chart.properties["width"], "500px")
        self.assertEqual(chart.properties["height"], "400px")

    def test_render_no_options(self):
        content = {"type": "scatter", "data": []}
        components = self.renderer.render(content, surface_id="s1")
        chart = components[0]
        self.assertNotIn("options", chart.properties)

    def test_unique_ids(self):
        content = {"type": "bar", "data": [], "title": "Test"}
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)))

    def test_id_prefixes(self):
        content = {"type": "bar", "data": [], "title": "T"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("chart-title-"))
        self.assertTrue(components[1].id.startswith("chart-"))


if __name__ == "__main__":
    unittest.main()
