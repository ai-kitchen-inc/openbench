"""Tests for TextRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.text import TextRenderer


class TestTextRendererRegistry(unittest.TestCase):
    """Tests for TextRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("text" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("text", "default")
        self.assertIsInstance(renderer, TextRenderer)


class TestTextRenderer(unittest.TestCase):
    """Tests for TextRenderer."""

    def setUp(self):
        self.renderer = TextRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "text")

    # -- detect --

    def test_detect_plain_string(self):
        self.assertTrue(self.renderer.detect("hello world"))

    def test_detect_rejects_empty(self):
        self.assertFalse(self.renderer.detect(""))
        self.assertFalse(self.renderer.detect("   "))

    def test_detect_rejects_non_string(self):
        self.assertFalse(self.renderer.detect({"type": "bar"}))
        self.assertFalse(self.renderer.detect(123))
        self.assertFalse(self.renderer.detect(None))

    # -- simple text --

    def test_render_simple_text_is_single_text_component(self):
        components = self.renderer.render("just a sentence", surface_id="s1")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "just a sentence")
        self.assertEqual(components[0].properties["variant"], "body")

    def test_render_heading_uses_semantic_variant(self):
        components = self.renderer.render("# Title\n\nbody text", surface_id="s1")
        # heading component + body component
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["variant"], "h1")
        self.assertEqual(components[0].properties["text"], "Title")
        self.assertTrue(any(c.properties.get("variant") == "body" for c in components))

    def test_render_multiple_heading_levels(self):
        components = self.renderer.render("## Section\ntext\n### Sub", surface_id="s1")
        variants = [c.properties["variant"] for c in components]
        self.assertIn("h2", variants)
        self.assertIn("h3", variants)

    # -- complex markdown -> ObMarkdown --

    def test_render_code_fence_uses_obmarkdown(self):
        components = self.renderer.render("```python\nprint(1)\n```", surface_id="s1")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].component, "ObMarkdown")
        self.assertIn("```", components[0].properties["content"])

    def test_render_table_uses_obmarkdown(self):
        components = self.renderer.render("| a | b |\n| 1 | 2 |", surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_link_uses_obmarkdown(self):
        components = self.renderer.render("see [docs](https://x.test)", surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_bold_uses_obmarkdown(self):
        components = self.renderer.render("this is **bold**", surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_generated_ids_are_unique(self):
        components = self.renderer.render("# A\nbody\n# B", surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
