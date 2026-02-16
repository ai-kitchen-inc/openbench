"""Tests for ListRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.list import ListRenderer


class TestListRendererRegistry(unittest.TestCase):
    """Tests for ListRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("list" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("list", "default")
        self.assertIsInstance(renderer, ListRenderer)


class TestListRenderer(unittest.TestCase):
    """Tests for ListRenderer."""

    def setUp(self):
        self.renderer = ListRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "list")

    # -- detect --

    def test_detect_valid(self):
        self.assertTrue(self.renderer.detect({"listType": "unordered", "items": ["a", "b"]}))

    def test_detect_ordered(self):
        self.assertTrue(self.renderer.detect({"listType": "ordered", "items": ["first"]}))

    def test_detect_missing_items(self):
        self.assertFalse(self.renderer.detect({"listType": "unordered"}))

    def test_detect_empty_items(self):
        self.assertFalse(self.renderer.detect({"listType": "unordered", "items": []}))

    def test_detect_missing_list_type(self):
        self.assertFalse(self.renderer.detect({"items": ["a", "b"]}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("some string"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_empty_dict(self):
        self.assertFalse(self.renderer.detect({}))

    def test_detect_does_not_clash_with_chart(self):
        self.assertFalse(self.renderer.detect({"type": "bar", "data": []}))

    def test_detect_does_not_clash_with_form(self):
        self.assertFalse(self.renderer.detect({"fields": [{"name": "x"}], "title": "Form"}))

    # -- render string items --

    def test_render_string_items(self):
        content = {"listType": "unordered", "items": ["Alpha", "Beta", "Gamma"]}
        components = self.renderer.render(content, surface_id="s1")

        # Should have: Card, List, 3 Text items = 5 components
        self.assertEqual(len(components), 5)

        # Card wraps the list
        card = components[0]
        self.assertEqual(card.component, "Card")
        self.assertEqual(card.properties["elevation"], 0)

        # List component
        list_comp = components[1]
        self.assertEqual(list_comp.component, "List")
        self.assertFalse(list_comp.properties["ordered"])
        self.assertEqual(len(list_comp.properties["children"]), 3)

        # Text children
        for i, text in enumerate(["Alpha", "Beta", "Gamma"]):
            self.assertEqual(components[2 + i].component, "Text")
            self.assertEqual(components[2 + i].properties["text"], text)
            self.assertEqual(components[2 + i].properties["variant"], "body")

    def test_render_ordered(self):
        content = {"listType": "ordered", "items": ["First", "Second"]}
        components = self.renderer.render(content, surface_id="s1")
        list_comp = next(c for c in components if c.component == "List")
        self.assertTrue(list_comp.properties["ordered"])

    def test_render_unordered(self):
        content = {"listType": "unordered", "items": ["A"]}
        components = self.renderer.render(content, surface_id="s1")
        list_comp = next(c for c in components if c.component == "List")
        self.assertFalse(list_comp.properties["ordered"])

    # -- render dict items with subtitle --

    def test_render_dict_items(self):
        content = {
            "listType": "unordered",
            "items": [{"text": "Item A"}, {"text": "Item B"}],
        }
        components = self.renderer.render(content, surface_id="s1")
        texts = [c for c in components if c.component == "Text"]
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts[0].properties["text"], "Item A")
        self.assertEqual(texts[1].properties["text"], "Item B")

    def test_render_dict_items_with_subtitle(self):
        content = {
            "listType": "unordered",
            "items": [
                {"text": "Solar Energy", "subtitle": "Renewable, abundant"},
                {"text": "Wind Energy", "subtitle": "Growing rapidly"},
            ],
        }
        components = self.renderer.render(content, surface_id="s1")

        # Should have: Card, List, 2x (Column, Text, Text) = 2 + 2*3 = 8 components
        self.assertEqual(len(components), 8)

        columns = [c for c in components if c.component == "Column"]
        self.assertEqual(len(columns), 2)

        # Each Column should have 2 children
        for col in columns:
            self.assertEqual(len(col.properties["children"]), 2)
            self.assertEqual(col.properties["gap"], "2px")

        # Check text content
        texts = [c for c in components if c.component == "Text"]
        bodies = [t for t in texts if t.properties["variant"] == "body"]
        captions = [t for t in texts if t.properties["variant"] == "caption"]
        self.assertEqual(len(bodies), 2)
        self.assertEqual(len(captions), 2)
        self.assertEqual(bodies[0].properties["text"], "Solar Energy")
        self.assertEqual(captions[0].properties["text"], "Renewable, abundant")

    # -- render with title --

    def test_render_with_title(self):
        content = {
            "listType": "unordered",
            "title": "My List",
            "items": ["A"],
        }
        components = self.renderer.render(content, surface_id="s1")
        title = components[0]
        self.assertEqual(title.component, "Text")
        self.assertEqual(title.properties["text"], "My List")
        self.assertEqual(title.properties["variant"], "h4")

    def test_render_without_title(self):
        content = {"listType": "unordered", "items": ["A"]}
        components = self.renderer.render(content, surface_id="s1")
        # First component should be Card, not Text title
        self.assertEqual(components[0].component, "Card")

    # -- render maxHeight --

    def test_render_max_height(self):
        content = {
            "listType": "unordered",
            "items": ["A"],
            "maxHeight": "200px",
        }
        components = self.renderer.render(content, surface_id="s1")
        list_comp = next(c for c in components if c.component == "List")
        self.assertEqual(list_comp.properties["maxHeight"], "200px")

    def test_render_no_max_height(self):
        content = {"listType": "unordered", "items": ["A"]}
        components = self.renderer.render(content, surface_id="s1")
        list_comp = next(c for c in components if c.component == "List")
        self.assertNotIn("maxHeight", list_comp.properties)

    # -- unique IDs --

    def test_unique_ids(self):
        content = {
            "listType": "unordered",
            "title": "Test",
            "items": ["A", "B", {"text": "C", "subtitle": "sub"}],
        }
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate IDs found: {ids}")

    def test_id_prefixes(self):
        content = {"listType": "unordered", "title": "T", "items": ["A"]}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("list-title-"))
        self.assertTrue(components[1].id.startswith("list-card-"))
        self.assertTrue(components[2].id.startswith("list-"))
        self.assertTrue(components[3].id.startswith("list-item-"))

    # -- children reference integrity --

    def test_list_children_reference_existing_ids(self):
        content = {"listType": "unordered", "items": ["A", "B"]}
        components = self.renderer.render(content, surface_id="s1")
        list_comp = next(c for c in components if c.component == "List")
        all_ids = {c.id for c in components}
        for child_id in list_comp.properties["children"]:
            self.assertIn(child_id, all_ids, f"Child {child_id} not in component IDs")

    def test_card_children_reference_list(self):
        content = {"listType": "unordered", "items": ["A"]}
        components = self.renderer.render(content, surface_id="s1")
        card = next(c for c in components if c.component == "Card")
        list_comp = next(c for c in components if c.component == "List")
        self.assertIn(list_comp.id, card.properties["children"])


if __name__ == "__main__":
    unittest.main()
