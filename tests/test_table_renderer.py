"""Tests for TableRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.table import TableRenderer


class TestTableRendererRegistry(unittest.TestCase):
    """Tests for TableRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("table" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("table", "default")
        self.assertIsInstance(renderer, TableRenderer)


class TestTableRenderer(unittest.TestCase):
    """Tests for TableRenderer."""

    def setUp(self):
        self.renderer = TableRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "table")

    # -- detect --

    def test_detect_valid(self):
        self.assertTrue(self.renderer.detect({"headers": ["A", "B"], "rows": [["1", "2"]]}))

    def test_detect_empty_rows(self):
        self.assertTrue(self.renderer.detect({"headers": ["A"], "rows": []}))

    def test_detect_missing_headers(self):
        self.assertFalse(self.renderer.detect({"rows": [["1"]]}))

    def test_detect_empty_headers(self):
        self.assertFalse(self.renderer.detect({"headers": [], "rows": [["1"]]}))

    def test_detect_missing_rows(self):
        self.assertFalse(self.renderer.detect({"headers": ["A"]}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("table"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_does_not_clash_with_chart(self):
        self.assertFalse(self.renderer.detect({"type": "bar", "data": []}))

    def test_detect_does_not_clash_with_list(self):
        self.assertFalse(self.renderer.detect({"listType": "ordered", "items": ["a"]}))

    def test_detect_does_not_clash_with_form(self):
        self.assertFalse(self.renderer.detect({"fields": [{"name": "x"}], "title": "Form"}))

    # -- render --

    def test_render_basic(self):
        content = {
            "headers": ["Name", "Value"],
            "rows": [["Solar", "0.03"], ["Wind", "0.034"]],
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        table = components[0]
        self.assertEqual(table.component, "ObTable")
        self.assertEqual(table.properties["headers"], ["Name", "Value"])
        self.assertEqual(len(table.properties["rows"]), 2)

    def test_render_with_title(self):
        content = {
            "headers": ["A"],
            "rows": [["1"]],
            "title": "My Table",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "My Table")
        self.assertEqual(components[0].properties["variant"], "h4")
        self.assertEqual(components[1].component, "ObTable")

    def test_render_with_caption(self):
        content = {
            "headers": ["A"],
            "rows": [["1"]],
            "caption": "Source: data.gov",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "Source: data.gov")
        self.assertEqual(components[0].properties["variant"], "caption")
        self.assertEqual(components[1].component, "ObTable")

    def test_render_with_title_and_caption(self):
        content = {
            "headers": ["A"],
            "rows": [["1"]],
            "title": "Title",
            "caption": "Caption",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 3)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["variant"], "h4")
        self.assertEqual(components[1].component, "Text")
        self.assertEqual(components[1].properties["variant"], "caption")
        self.assertEqual(components[2].component, "ObTable")

    def test_striped_default_true(self):
        content = {"headers": ["A"], "rows": [["1"]]}
        components = self.renderer.render(content, surface_id="s1")
        table = components[0]
        self.assertTrue(table.properties["striped"])

    def test_compact_default_false(self):
        content = {"headers": ["A"], "rows": [["1"]]}
        components = self.renderer.render(content, surface_id="s1")
        table = components[0]
        self.assertFalse(table.properties["compact"])

    def test_custom_striped_false(self):
        content = {"headers": ["A"], "rows": [["1"]], "striped": False}
        components = self.renderer.render(content, surface_id="s1")
        table = components[0]
        self.assertFalse(table.properties["striped"])

    def test_custom_compact_true(self):
        content = {"headers": ["A"], "rows": [["1"]], "compact": True}
        components = self.renderer.render(content, surface_id="s1")
        table = components[0]
        self.assertTrue(table.properties["compact"])

    def test_empty_rows(self):
        content = {"headers": ["A", "B"], "rows": []}
        components = self.renderer.render(content, surface_id="s1")
        table = components[0]
        self.assertEqual(table.properties["rows"], [])

    def test_unique_ids(self):
        content = {"headers": ["A"], "rows": [["1"]], "title": "T", "caption": "C"}
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate IDs found: {ids}")

    def test_id_prefixes(self):
        content = {"headers": ["A"], "rows": [["1"]], "title": "T", "caption": "C"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("table-title-"))
        self.assertTrue(components[1].id.startswith("table-caption-"))
        self.assertTrue(components[2].id.startswith("table-"))


if __name__ == "__main__":
    unittest.main()
