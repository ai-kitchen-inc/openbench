"""Tests for TabsRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.tabs import TabsRenderer


class TestTabsRendererRegistry(unittest.TestCase):
    """Tests for TabsRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("tabs" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("tabs", "default")
        self.assertIsInstance(renderer, TabsRenderer)


class TestTabsRenderer(unittest.TestCase):
    """Tests for TabsRenderer."""

    def setUp(self):
        self.renderer = TabsRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "tabs")

    # -- detect --

    def test_detect_valid(self):
        self.assertTrue(
            self.renderer.detect(
                {
                    "tabs": [
                        {"label": "Tab A", "content": "Content A"},
                        {"label": "Tab B", "content": "Content B"},
                    ]
                }
            )
        )

    def test_detect_single_tab(self):
        self.assertTrue(self.renderer.detect({"tabs": [{"label": "Only"}]}))

    def test_detect_missing_tabs(self):
        self.assertFalse(self.renderer.detect({"title": "No tabs"}))

    def test_detect_empty_tabs(self):
        self.assertFalse(self.renderer.detect({"tabs": []}))

    def test_detect_tabs_not_list(self):
        self.assertFalse(self.renderer.detect({"tabs": "not a list"}))

    def test_detect_tabs_without_label(self):
        self.assertFalse(self.renderer.detect({"tabs": [{"content": "no label"}]}))

    def test_detect_mixed_valid_invalid(self):
        # All tabs must have "label"
        self.assertFalse(
            self.renderer.detect(
                {
                    "tabs": [
                        {"label": "Valid"},
                        {"content": "Missing label"},
                    ]
                }
            )
        )

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("some string"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_empty_dict(self):
        self.assertFalse(self.renderer.detect({}))

    def test_detect_does_not_clash_with_form(self):
        self.assertFalse(self.renderer.detect({"fields": [{"name": "x"}], "title": "Form"}))

    def test_detect_does_not_clash_with_list(self):
        self.assertFalse(self.renderer.detect({"items": ["a"], "listType": "ordered"}))

    # -- render --

    def test_render_basic(self):
        content = {
            "tabs": [
                {"label": "Solar", "content": "Solar energy info"},
                {"label": "Wind", "content": "Wind energy info"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")

        # Should have: Tabs + 2 ObMarkdown children = 3 components
        self.assertEqual(len(components), 3)

        # Tabs component
        tabs_comp = components[0]
        self.assertEqual(tabs_comp.component, "Tabs")
        self.assertEqual(len(tabs_comp.properties["tabs"]), 2)
        self.assertEqual(tabs_comp.properties["tabs"][0]["label"], "Solar")
        self.assertEqual(tabs_comp.properties["tabs"][1]["label"], "Wind")
        self.assertEqual(len(tabs_comp.properties["children"]), 2)

        # ObMarkdown children
        self.assertEqual(components[1].component, "ObMarkdown")
        self.assertEqual(components[1].properties["content"], "Solar energy info")
        self.assertEqual(components[2].component, "ObMarkdown")
        self.assertEqual(components[2].properties["content"], "Wind energy info")

    def test_render_with_title(self):
        content = {
            "title": "Energy Comparison",
            "tabs": [{"label": "Solar", "content": "Info"}],
        }
        components = self.renderer.render(content, surface_id="s1")

        # Should have: Text(h4) title + Tabs + 1 ObMarkdown = 3 components
        self.assertEqual(len(components), 3)

        title = components[0]
        self.assertEqual(title.component, "Text")
        self.assertEqual(title.properties["text"], "Energy Comparison")
        self.assertEqual(title.properties["variant"], "h4")

        self.assertEqual(components[1].component, "Tabs")

    def test_render_without_title(self):
        content = {"tabs": [{"label": "Only", "content": "Content"}]}
        components = self.renderer.render(content, surface_id="s1")

        # First component should be Tabs, not Text title
        self.assertEqual(components[0].component, "Tabs")

    def test_render_tab_without_content(self):
        content = {"tabs": [{"label": "Empty Tab"}]}
        components = self.renderer.render(content, surface_id="s1")

        # Should still render with empty string content
        md = next(c for c in components if c.component == "ObMarkdown")
        self.assertEqual(md.properties["content"], "")

    def test_render_tab_labels_only_in_tabs_prop(self):
        content = {
            "tabs": [
                {"label": "A", "content": "Content A"},
                {"label": "B", "content": "Content B"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        tabs_comp = next(c for c in components if c.component == "Tabs")

        # tabs property should only have label, not content
        for tab_def in tabs_comp.properties["tabs"]:
            self.assertIn("label", tab_def)
            self.assertNotIn("content", tab_def)

    # -- children reference integrity --

    def test_tabs_children_reference_existing_ids(self):
        content = {
            "tabs": [
                {"label": "A", "content": "Content A"},
                {"label": "B", "content": "Content B"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        tabs_comp = next(c for c in components if c.component == "Tabs")
        all_ids = {c.id for c in components}
        for child_id in tabs_comp.properties["children"]:
            self.assertIn(child_id, all_ids, f"Child {child_id} not in component IDs")

    def test_children_count_matches_tabs_count(self):
        content = {
            "tabs": [
                {"label": "A", "content": "X"},
                {"label": "B", "content": "Y"},
                {"label": "C", "content": "Z"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        tabs_comp = next(c for c in components if c.component == "Tabs")
        self.assertEqual(
            len(tabs_comp.properties["children"]),
            len(tabs_comp.properties["tabs"]),
        )

    # -- unique IDs --

    def test_unique_ids(self):
        content = {
            "title": "Test Tabs",
            "tabs": [
                {"label": "A", "content": "Content A"},
                {"label": "B", "content": "Content B"},
                {"label": "C", "content": "Content C"},
            ],
        }
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate IDs found: {ids}")

    def test_id_prefixes(self):
        content = {
            "title": "T",
            "tabs": [{"label": "Tab", "content": "C"}],
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("tabs-title-"))
        self.assertTrue(components[1].id.startswith("tabs-"))
        self.assertTrue(components[2].id.startswith("tab-panel-"))


if __name__ == "__main__":
    unittest.main()
