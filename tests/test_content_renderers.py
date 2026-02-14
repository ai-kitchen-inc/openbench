"""Tests for content renderers (base + text)."""

import unittest

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry
from openbench.chat.renderers.text import TextRenderer


class TestContentRendererRegistry(unittest.TestCase):
    """Tests for ContentRendererRegistry."""

    def test_text_renderer_registered(self):
        """TextRenderer should be auto-registered via decorator."""
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(
            any("text" in p for p in plugins),
            f"TextRenderer not found in registry. Registered: {plugins}",
        )

    def test_create_text_renderer(self):
        renderer = ContentRendererRegistry.create("text", "default")
        self.assertIsInstance(renderer, TextRenderer)
        self.assertEqual(renderer.content_type, "text")


class TestTextRenderer(unittest.TestCase):
    """Tests for TextRenderer."""

    def setUp(self):
        self.renderer = TextRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "text")

    # -- detect --

    def test_detect_plain_text(self):
        self.assertTrue(self.renderer.detect("Hello world"))

    def test_detect_markdown(self):
        self.assertTrue(self.renderer.detect("# Heading\nBody text"))

    def test_detect_empty_string(self):
        self.assertFalse(self.renderer.detect(""))

    def test_detect_whitespace_only(self):
        self.assertFalse(self.renderer.detect("   \n\t  "))

    def test_detect_non_string(self):
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))
        self.assertFalse(self.renderer.detect({"key": "val"}))

    # -- render simple text --

    def test_render_plain_text(self):
        components = self.renderer.render("Hello world", surface_id="s1")
        self.assertTrue(len(components) >= 1)
        self.assertIsInstance(components[0], A2UIComponent)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "Hello world")
        self.assertEqual(components[0].properties["variant"], "body")

    def test_render_heading(self):
        components = self.renderer.render("# Title", surface_id="s1")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].properties["variant"], "h1")
        self.assertEqual(components[0].properties["text"], "Title")

    def test_render_multiple_headings(self):
        text = "# Title\nSome body\n## Subtitle\nMore body"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(len(components), 4)
        self.assertEqual(components[0].properties["variant"], "h1")
        self.assertEqual(components[1].properties["variant"], "body")
        self.assertEqual(components[2].properties["variant"], "h2")
        self.assertEqual(components[3].properties["variant"], "body")

    def test_render_heading_levels(self):
        for level in range(1, 6):
            prefix = "#" * level
            components = self.renderer.render(f"{prefix} Heading {level}", surface_id="s1")
            self.assertEqual(components[0].properties["variant"], f"h{level}")

    # -- render complex markdown --

    def test_render_code_fence(self):
        text = "Here is code:\n```python\nprint('hello')\n```"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].component, "ObMarkdown")
        self.assertEqual(components[0].properties["content"], text)

    def test_render_table(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_links(self):
        text = "Visit [OpenBench](https://openbench.dev) for docs"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_list(self):
        text = "Items:\n- First\n- Second\n- Third"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_blockquote(self):
        text = "> This is a quote"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    # -- component IDs --

    def test_unique_ids(self):
        components = self.renderer.render("# Title\nBody\n## Sub\nMore", surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)), "Component IDs must be unique")

    def test_id_prefixes(self):
        """Text components should have 'txt-' prefix, markdown 'md-'."""
        text_components = self.renderer.render("Hello", surface_id="s1")
        self.assertTrue(text_components[0].id.startswith("txt-"))

        md_components = self.renderer.render("```\ncode\n```", surface_id="s1")
        self.assertTrue(md_components[0].id.startswith("md-"))

    # -- LaTeX detection --

    def test_render_inline_math(self):
        """Inline math ($...$) should be detected as complex markdown."""
        text = "The formula is $E = mc^2$ here."
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_display_math(self):
        """Display math ($$...$$) should be detected as complex markdown."""
        text = "$$\\sum_{i=1}^n x_i$$"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_latex_paren(self):
        """LaTeX inline math (\\(...\\)) should be detected as complex markdown."""
        text = "The formula is \\(f(x) = x^2\\) here."
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_render_latex_bracket(self):
        """LaTeX display math (\\[...\\]) should be detected as complex markdown."""
        text = "\\[a^2 + b^2 = c^2\\]"
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")

    def test_dollar_sign_not_math(self):
        """A lone dollar sign like 'Price is $50' should NOT trigger math detection."""
        text = "Price is $50"
        components = self.renderer.render(text, surface_id="s1")
        # Should remain simple text, not ObMarkdown
        self.assertEqual(components[0].component, "Text")

    def test_currency_multiple_dollars_not_math(self):
        """Multiple currency amounts like '$0.03/kWh ... $0.034/kWh' should NOT be math."""
        text = "Solar costs $0.03/kWh for solar and $0.034/kWh for wind."
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "Text")

    def test_currency_with_commas_not_math(self):
        """Currency with commas like '$1,000' should NOT trigger math."""
        text = "The budget is $1,000 and expenses are $500."
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "Text")

    def test_render_mixed_math_and_text(self):
        """Text with both markdown headings and math should use ObMarkdown."""
        text = "The quadratic formula is $x = \\frac{-b}{2a}$ and it works."
        components = self.renderer.render(text, surface_id="s1")
        self.assertEqual(components[0].component, "ObMarkdown")


if __name__ == "__main__":
    unittest.main()
