"""Tests for FileRenderer."""

import unittest

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.file import FileRenderer


class TestFileRendererRegistry(unittest.TestCase):
    """Tests for FileRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("file" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("file", "default")
        self.assertIsInstance(renderer, FileRenderer)


class TestFileRenderer(unittest.TestCase):
    """Tests for FileRenderer."""

    def setUp(self):
        self.renderer = FileRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "file")

    # -- detect --

    def test_detect_single_file(self):
        self.assertTrue(self.renderer.detect({"name": "report.pdf", "url": "https://example.com/report.pdf"}))

    def test_detect_file_list(self):
        self.assertTrue(self.renderer.detect([
            {"name": "a.pdf", "url": "https://example.com/a.pdf"},
            {"name": "b.csv", "url": "https://example.com/b.csv"},
        ]))

    def test_detect_missing_name(self):
        self.assertFalse(self.renderer.detect({"url": "https://example.com/file.pdf"}))

    def test_detect_missing_url(self):
        self.assertFalse(self.renderer.detect({"name": "file.pdf"}))

    def test_detect_empty_list(self):
        self.assertFalse(self.renderer.detect([]))

    def test_detect_invalid_list_item(self):
        self.assertFalse(self.renderer.detect([{"name": "a.pdf"}]))  # missing url

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("file.pdf"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    # -- render single file --

    def test_render_single_file(self):
        content = {
            "name": "report.pdf",
            "url": "https://example.com/report.pdf",
            "size": 2048,
            "mimeType": "application/pdf",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        card = components[0]
        self.assertEqual(card.component, "ObFileCard")
        self.assertEqual(card.properties["fileName"], "report.pdf")
        self.assertEqual(card.properties["fileUrl"], "https://example.com/report.pdf")
        self.assertEqual(card.properties["fileSize"], 2048)
        self.assertEqual(card.properties["mimeType"], "application/pdf")

    def test_render_minimal_file(self):
        content = {"name": "data.csv", "url": "https://example.com/data.csv"}
        components = self.renderer.render(content, surface_id="s1")
        card = components[0]
        self.assertEqual(card.properties["fileName"], "data.csv")
        self.assertNotIn("fileSize", card.properties)
        self.assertNotIn("mimeType", card.properties)

    def test_render_with_preview(self):
        content = {
            "name": "photo.jpg",
            "url": "https://example.com/photo.jpg",
            "mimeType": "image/jpeg",
            "previewUrl": "https://example.com/thumb/photo.jpg",
        }
        components = self.renderer.render(content, surface_id="s1")
        card = components[0]
        self.assertEqual(card.properties["previewUrl"], "https://example.com/thumb/photo.jpg")

    # -- render multiple files --

    def test_render_multiple_files(self):
        content = [
            {"name": "a.pdf", "url": "https://example.com/a.pdf", "size": 1024},
            {"name": "b.csv", "url": "https://example.com/b.csv", "size": 512},
            {"name": "c.zip", "url": "https://example.com/c.zip"},
        ]
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 3)
        for comp in components:
            self.assertEqual(comp.component, "ObFileCard")

        self.assertEqual(components[0].properties["fileName"], "a.pdf")
        self.assertEqual(components[1].properties["fileName"], "b.csv")
        self.assertEqual(components[2].properties["fileName"], "c.zip")

    def test_unique_ids(self):
        content = [
            {"name": "a.pdf", "url": "https://example.com/a"},
            {"name": "b.pdf", "url": "https://example.com/b"},
        ]
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)))

    def test_id_prefix(self):
        content = {"name": "test.pdf", "url": "https://example.com/test.pdf"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("file-"))


if __name__ == "__main__":
    unittest.main()
