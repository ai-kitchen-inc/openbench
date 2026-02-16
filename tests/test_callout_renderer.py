"""Tests for CalloutRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.callout import CalloutRenderer


class TestCalloutRendererRegistry(unittest.TestCase):
    """Tests for CalloutRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("callout" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("callout", "default")
        self.assertIsInstance(renderer, CalloutRenderer)


class TestCalloutRenderer(unittest.TestCase):
    """Tests for CalloutRenderer."""

    def setUp(self):
        self.renderer = CalloutRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "callout")

    # -- detect --

    def test_detect_valid(self):
        self.assertTrue(self.renderer.detect({"calloutContent": "Important note"}))

    def test_detect_with_variant(self):
        self.assertTrue(self.renderer.detect({"calloutContent": "Warning!", "variant": "warning"}))

    def test_detect_empty_content(self):
        self.assertFalse(self.renderer.detect({"calloutContent": ""}))

    def test_detect_missing_content(self):
        self.assertFalse(self.renderer.detect({"variant": "info"}))

    def test_detect_not_string_content(self):
        self.assertFalse(self.renderer.detect({"calloutContent": 42}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("callout"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_does_not_clash_with_modal(self):
        self.assertFalse(self.renderer.detect({"modalContent": "text", "modalTitle": "Title"}))

    def test_detect_does_not_clash_with_form(self):
        self.assertFalse(self.renderer.detect({"fields": [{"name": "x"}], "title": "Form"}))

    # -- render --

    def test_render_basic(self):
        content = {"calloutContent": "This is important."}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        callout = components[0]
        self.assertEqual(callout.component, "ObCallout")
        self.assertEqual(callout.properties["content"], "This is important.")
        self.assertEqual(callout.properties["variant"], "default")

    def test_render_info_variant(self):
        content = {"calloutContent": "FYI", "variant": "info"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["variant"], "info")

    def test_render_success_variant(self):
        content = {"calloutContent": "Done!", "variant": "success"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["variant"], "success")

    def test_render_warning_variant(self):
        content = {"calloutContent": "Careful!", "variant": "warning"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["variant"], "warning")

    def test_render_default_variant(self):
        content = {"calloutContent": "Note", "variant": "default"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["variant"], "default")

    def test_render_invalid_variant_defaults(self):
        content = {"calloutContent": "Note", "variant": "danger"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["variant"], "default")

    def test_render_with_title(self):
        content = {"calloutContent": "Details here.", "title": "Note"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["title"], "Note")

    def test_render_without_title(self):
        content = {"calloutContent": "No title"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertNotIn("title", components[0].properties)

    def test_single_component_output(self):
        content = {"calloutContent": "Single", "variant": "info", "title": "T"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)

    def test_unique_ids(self):
        content = {"calloutContent": "A"}
        c1 = self.renderer.render(content, surface_id="s1")
        c2 = self.renderer.render(content, surface_id="s2")
        self.assertNotEqual(c1[0].id, c2[0].id)

    def test_id_prefix(self):
        content = {"calloutContent": "Test"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("callout-"))


if __name__ == "__main__":
    unittest.main()
