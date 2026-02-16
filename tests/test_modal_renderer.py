"""Tests for ModalRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.modal import ModalRenderer


class TestModalRendererRegistry(unittest.TestCase):
    """Tests for ModalRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("modal" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("modal", "default")
        self.assertIsInstance(renderer, ModalRenderer)


class TestModalRenderer(unittest.TestCase):
    """Tests for ModalRenderer."""

    def setUp(self):
        self.renderer = ModalRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "modal")

    # -- detect --

    def test_detect_valid(self):
        self.assertTrue(self.renderer.detect({"modalContent": "Some important info"}))

    def test_detect_with_title(self):
        self.assertTrue(
            self.renderer.detect(
                {
                    "modalContent": "Content here",
                    "modalTitle": "Important",
                }
            )
        )

    def test_detect_missing_modal_content(self):
        self.assertFalse(self.renderer.detect({"modalTitle": "No content"}))

    def test_detect_empty_content(self):
        self.assertFalse(self.renderer.detect({"modalContent": ""}))

    def test_detect_content_not_string(self):
        self.assertFalse(self.renderer.detect({"modalContent": 42}))
        self.assertFalse(self.renderer.detect({"modalContent": ["list"]}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("some string"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_empty_dict(self):
        self.assertFalse(self.renderer.detect({}))

    def test_detect_does_not_clash_with_form(self):
        self.assertFalse(self.renderer.detect({"fields": [{"name": "x"}], "title": "Form"}))

    def test_detect_does_not_clash_with_tabs(self):
        self.assertFalse(self.renderer.detect({"tabs": [{"label": "Tab"}]}))

    # -- render --

    def test_render_basic(self):
        content = {"modalContent": "Hello **world**"}
        components = self.renderer.render(content, surface_id="s1")

        # Should have: Modal + ObMarkdown child = 2 components
        self.assertEqual(len(components), 2)

        # Modal component
        modal = components[0]
        self.assertEqual(modal.component, "Modal")
        self.assertTrue(modal.properties["open"])
        self.assertEqual(len(modal.properties["children"]), 1)

        # ObMarkdown child
        md = components[1]
        self.assertEqual(md.component, "ObMarkdown")
        self.assertEqual(md.properties["content"], "Hello **world**")

    def test_render_with_title(self):
        content = {"modalContent": "Body text", "modalTitle": "Important Notice"}
        components = self.renderer.render(content, surface_id="s1")

        modal = next(c for c in components if c.component == "Modal")
        self.assertEqual(modal.properties["title"], "Important Notice")

    def test_render_without_title(self):
        content = {"modalContent": "No title modal"}
        components = self.renderer.render(content, surface_id="s1")

        modal = next(c for c in components if c.component == "Modal")
        self.assertNotIn("title", modal.properties)

    def test_render_open_true(self):
        content = {"modalContent": "Content"}
        components = self.renderer.render(content, surface_id="s1")

        modal = next(c for c in components if c.component == "Modal")
        self.assertTrue(modal.properties["open"])

    # -- children reference integrity --

    def test_modal_children_reference_existing_ids(self):
        content = {"modalContent": "Test content"}
        components = self.renderer.render(content, surface_id="s1")
        modal = next(c for c in components if c.component == "Modal")
        all_ids = {c.id for c in components}
        for child_id in modal.properties["children"]:
            self.assertIn(child_id, all_ids, f"Child {child_id} not in component IDs")

    def test_child_is_ob_markdown(self):
        content = {"modalContent": "Markdown body"}
        components = self.renderer.render(content, surface_id="s1")
        modal = next(c for c in components if c.component == "Modal")
        child_id = modal.properties["children"][0]
        child = next(c for c in components if c.id == child_id)
        self.assertEqual(child.component, "ObMarkdown")
        self.assertEqual(child.properties["content"], "Markdown body")

    # -- unique IDs --

    def test_unique_ids(self):
        content = {"modalContent": "Test", "modalTitle": "Title"}
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate IDs found: {ids}")

    def test_id_prefixes(self):
        content = {"modalContent": "Test"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("modal-"))
        self.assertTrue(components[1].id.startswith("modal-body-"))


if __name__ == "__main__":
    unittest.main()
