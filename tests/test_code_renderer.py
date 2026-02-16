"""Tests for CodeRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.code import CodeRenderer


class TestCodeRendererRegistry(unittest.TestCase):
    """Tests for CodeRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("code" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("code", "default")
        self.assertIsInstance(renderer, CodeRenderer)


class TestCodeRenderer(unittest.TestCase):
    """Tests for CodeRenderer."""

    def setUp(self):
        self.renderer = CodeRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "code")

    # -- detect --

    def test_detect_python(self):
        self.assertTrue(self.renderer.detect({"code": "print('hi')", "language": "python"}))

    def test_detect_javascript(self):
        self.assertTrue(self.renderer.detect({"code": "console.log(1)", "language": "javascript"}))

    def test_detect_missing_language(self):
        self.assertFalse(self.renderer.detect({"code": "print('hi')"}))

    def test_detect_missing_code(self):
        self.assertFalse(self.renderer.detect({"language": "python"}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("some code"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_empty_dict(self):
        self.assertFalse(self.renderer.detect({}))

    def test_detect_does_not_clash_with_chart(self):
        """Ensure chart-like dicts are not matched (no 'code' + 'language' keys)."""
        self.assertFalse(self.renderer.detect({"type": "bar", "data": []}))

    # -- render --

    def test_render_basic(self):
        content = {"code": "print('hello')", "language": "python"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        block = components[0]
        self.assertEqual(block.component, "ObCodeBlock")
        self.assertEqual(block.properties["code"], "print('hello')")
        self.assertEqual(block.properties["language"], "python")
        self.assertTrue(block.properties["showLineNumbers"])
        self.assertEqual(block.properties["maxHeight"], "400px")

    def test_render_with_title(self):
        content = {"code": "x = 1", "language": "python", "title": "Example"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 2)
        # First: title text
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "Example")
        self.assertEqual(components[0].properties["variant"], "h4")
        # Second: code block
        self.assertEqual(components[1].component, "ObCodeBlock")

    def test_render_custom_options(self):
        content = {
            "code": "fn main() {}",
            "language": "rust",
            "showLineNumbers": False,
            "maxHeight": "200px",
        }
        components = self.renderer.render(content, surface_id="s1")
        block = components[0]
        self.assertFalse(block.properties["showLineNumbers"])
        self.assertEqual(block.properties["maxHeight"], "200px")

    def test_render_empty_code(self):
        content = {"code": "", "language": "python"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].properties["code"], "")

    def test_render_multiline_code(self):
        code = "def foo():\n    return 42\n\nprint(foo())"
        content = {"code": code, "language": "python"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["code"], code)

    def test_unique_ids(self):
        content = {"code": "x = 1", "language": "python", "title": "Test"}
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)))

    def test_id_prefixes(self):
        content = {"code": "x = 1", "language": "python", "title": "T"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("code-title-"))
        self.assertTrue(components[1].id.startswith("code-"))


if __name__ == "__main__":
    unittest.main()
