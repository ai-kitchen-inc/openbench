"""Tests for PDFGenerator and MarkdownGenerator."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from openbench.output.generators import MarkdownGenerator, PDFGenerator


class TestPDFGeneratorInit(unittest.TestCase):
    """Test PDFGenerator initialization."""

    def test_default_init(self):
        """Test default initialization."""
        generator = PDFGenerator()
        self.assertEqual(generator.template, "default")
        self.assertEqual(generator.page_size, "letter")
        self.assertEqual(generator.font_name, "Helvetica")
        self.assertEqual(generator.font_size, 11)

    def test_custom_init(self):
        """Test custom initialization."""
        generator = PDFGenerator(
            template="report",
            page_size="a4",
            font_name="Times",
            font_size=12,
            title_font_size=20,
            heading_font_size=16,
        )
        self.assertEqual(generator.template, "report")
        self.assertEqual(generator.page_size, "a4")
        self.assertEqual(generator.font_name, "Times")
        self.assertEqual(generator.font_size, 12)

    def test_custom_margins(self):
        """Test custom margins."""
        margins = {"top": 50, "bottom": 50, "left": 60, "right": 60}
        generator = PDFGenerator(margins=margins)
        self.assertEqual(generator.margins, margins)


class TestPDFGeneratorProperties(unittest.TestCase):
    """Test PDFGenerator properties."""

    def test_output_format(self):
        """Test output_format property."""
        generator = PDFGenerator()
        self.assertEqual(generator.output_format, "pdf")


class TestPDFGeneratorValidate(unittest.TestCase):
    """Test PDFGenerator validation."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = PDFGenerator()

    def test_validate_string(self):
        """Test validating string content."""
        self.assertTrue(self.generator.validate("Hello world"))

    def test_validate_dict(self):
        """Test validating dict content."""
        self.assertTrue(self.generator.validate({"key": "value"}))

    def test_validate_list(self):
        """Test validating list content."""
        self.assertTrue(self.generator.validate(["item1", "item2"]))

    def test_validate_none(self):
        """Test validating None content."""
        self.assertFalse(self.generator.validate(None))

    def test_validate_object_with_str(self):
        """Test validating object with __str__."""
        obj = MagicMock()
        obj.__str__ = lambda x: "content"
        self.assertTrue(self.generator.validate(obj))


class TestPDFGeneratorExtractContent(unittest.TestCase):
    """Test content extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = PDFGenerator()

    def test_extract_string(self):
        """Test extracting string content."""
        result = self.generator._extract_content("Simple text")
        self.assertEqual(result, "Simple text")

    def test_extract_dict_with_content(self):
        """Test extracting from dict with content key."""
        result = self.generator._extract_content({"content": "Text content"})
        self.assertEqual(result, "Text content")

    def test_extract_dict_with_intelligence_output(self):
        """Test extracting from IntelligenceLayer output."""
        input_data = {"intelligence_output": {"content": "AI output"}, "metadata": {}}
        result = self.generator._extract_content(input_data)
        self.assertEqual(result, "AI output")

    def test_extract_list(self):
        """Test extracting from list."""
        result = self.generator._extract_content(["item1", "item2", "item3"])
        self.assertIn("- item1", result)
        self.assertIn("- item2", result)
        self.assertIn("- item3", result)

    def test_extract_dict_with_raw_data(self):
        """Test extracting from DataLayer output."""
        mock_raw = MagicMock()
        mock_raw.content = "Raw content"
        input_data = {"raw_data": [mock_raw]}
        result = self.generator._extract_content(input_data)
        self.assertEqual(result, "Raw content")


class TestPDFGeneratorGenerate(unittest.TestCase):
    """Test PDF generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = PDFGenerator()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_creates_file(self):
        """Test that generate creates a file."""
        output_path = os.path.join(self.temp_dir, "test.pdf")
        result = self.generator.generate(content="Test content", output_path=output_path)

        self.assertTrue(os.path.exists(output_path))
        self.assertEqual(result.file_path, output_path)
        self.assertEqual(result.format, "pdf")
        self.assertGreater(result.size_bytes, 0)

    def test_generate_with_title(self):
        """Test generating PDF with title."""
        output_path = os.path.join(self.temp_dir, "titled.pdf")
        result = self.generator.generate(
            content="Content here", output_path=output_path, title="My Report"
        )

        self.assertEqual(result.metadata["title"], "My Report")

    def test_generate_with_author(self):
        """Test generating PDF with author."""
        output_path = os.path.join(self.temp_dir, "authored.pdf")
        result = self.generator.generate(
            content="Content", output_path=output_path, author="Test Author"
        )

        self.assertEqual(result.metadata["author"], "Test Author")

    def test_generate_with_template_override(self):
        """Test generating PDF with template override."""
        output_path = os.path.join(self.temp_dir, "report.pdf")
        result = self.generator.generate(
            content="Content", output_path=output_path, template="report"
        )

        self.assertEqual(result.metadata["template"], "report")

    def test_generate_creates_parent_directories(self):
        """Test that generate creates parent directories."""
        output_path = os.path.join(self.temp_dir, "subdir", "nested", "test.pdf")
        self.generator.generate(content="Content", output_path=output_path)

        self.assertTrue(os.path.exists(output_path))

    def test_generate_from_dict_content(self):
        """Test generating from dict content."""
        output_path = os.path.join(self.temp_dir, "dict.pdf")
        self.generator.generate(content={"content": "From dict"}, output_path=output_path)

        self.assertTrue(os.path.exists(output_path))

    def test_generate_from_intelligence_layer_output(self):
        """Test generating from IntelligenceLayer output."""
        output_path = os.path.join(self.temp_dir, "intel.pdf")
        input_data = {
            "intelligence_output": {"content": "AI generated text"},
            "metadata": {"layer": "intelligence"},
        }
        self.generator.generate(content=input_data, output_path=output_path, title="AI Report")

        self.assertTrue(os.path.exists(output_path))


class TestPDFGeneratorReportLab(unittest.TestCase):
    """Test ReportLab-specific functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = PDFGenerator(template="report")
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_with_headings(self):
        """Test generating PDF with markdown headings."""
        output_path = os.path.join(self.temp_dir, "headings.pdf")
        content = """# Main Title

## Section 1

This is section 1 content.

## Section 2

This is section 2 content."""

        self.generator.generate(content=content, output_path=output_path)

        self.assertTrue(os.path.exists(output_path))

    def test_generate_with_bullet_list(self):
        """Test generating PDF with bullet list."""
        output_path = os.path.join(self.temp_dir, "bullets.pdf")
        content = """Introduction paragraph.

- Item one
- Item two
- Item three

Conclusion paragraph."""

        self.generator.generate(content=content, output_path=output_path)

        self.assertTrue(os.path.exists(output_path))

    def test_generate_with_special_characters(self):
        """Test generating PDF with special characters."""
        output_path = os.path.join(self.temp_dir, "special.pdf")
        content = "Test with <special> & characters > here"

        self.generator.generate(content=content, output_path=output_path)

        self.assertTrue(os.path.exists(output_path))


class TestMarkdownGeneratorInit(unittest.TestCase):
    """Test MarkdownGenerator initialization."""

    def test_default_init(self):
        """Test default initialization."""
        generator = MarkdownGenerator()
        self.assertFalse(generator.add_toc)

    def test_with_toc(self):
        """Test initialization with TOC."""
        generator = MarkdownGenerator(add_toc=True)
        self.assertTrue(generator.add_toc)


class TestMarkdownGeneratorProperties(unittest.TestCase):
    """Test MarkdownGenerator properties."""

    def test_output_format(self):
        """Test output_format property."""
        generator = MarkdownGenerator()
        self.assertEqual(generator.output_format, "markdown")


class TestMarkdownGeneratorGenerate(unittest.TestCase):
    """Test Markdown generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = MarkdownGenerator()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_creates_file(self):
        """Test that generate creates a file."""
        output_path = os.path.join(self.temp_dir, "test.md")
        result = self.generator.generate(content="# Hello World", output_path=output_path)

        self.assertTrue(os.path.exists(output_path))
        self.assertEqual(result.file_path, output_path)
        self.assertEqual(result.format, "markdown")

    def test_generate_with_title(self):
        """Test generating markdown with title."""
        output_path = os.path.join(self.temp_dir, "titled.md")
        self.generator.generate(
            content="Content here", output_path=output_path, title="My Document"
        )

        with open(output_path) as f:
            content = f.read()

        self.assertIn("# My Document", content)
        self.assertIn("Generated:", content)

    def test_generate_from_dict(self):
        """Test generating from dict content."""
        output_path = os.path.join(self.temp_dir, "dict.md")
        self.generator.generate(content={"content": "Dict content"}, output_path=output_path)

        with open(output_path) as f:
            content = f.read()

        self.assertIn("Dict content", content)

    def test_generate_from_list(self):
        """Test generating from list content."""
        output_path = os.path.join(self.temp_dir, "list.md")
        self.generator.generate(content=["item1", "item2"], output_path=output_path)

        with open(output_path) as f:
            content = f.read()

        self.assertIn("- item1", content)
        self.assertIn("- item2", content)


class TestGeneratorIntegration(unittest.TestCase):
    """Integration tests for generators with workflow outputs."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pdf_from_google_adk_output(self):
        """Test generating PDF from GoogleADKAdapter output format."""
        generator = PDFGenerator(template="report")
        output_path = os.path.join(self.temp_dir, "adk_output.pdf")

        # Simulate GoogleADKAdapter output
        adk_output = {
            "content": "This is the AI-generated analysis of the document.",
            "model": "gemini-1.5-pro",
            "tokens_used": {"total_tokens": 500},
            "metadata": {"mode": "model"},
        }

        result = generator.generate(
            content=adk_output, output_path=output_path, title="AI Analysis Report"
        )

        self.assertTrue(os.path.exists(output_path))
        self.assertGreater(result.size_bytes, 0)

    def test_markdown_from_intelligence_layer_output(self):
        """Test generating Markdown from IntelligenceLayer output format."""
        generator = MarkdownGenerator()
        output_path = os.path.join(self.temp_dir, "intel_output.md")

        # Simulate IntelligenceLayer output
        intel_output = {
            "intelligence_output": {
                "content": "Summary of the document:\n\n1. Point one\n2. Point two",
                "model": "gemini-1.5-pro",
            },
            "metadata": {"layer": "intelligence"},
        }

        generator.generate(content=intel_output, output_path=output_path, title="Document Summary")

        self.assertTrue(os.path.exists(output_path))
        with open(output_path) as f:
            content = f.read()
        self.assertIn("Summary of the document", content)


if __name__ == "__main__":
    unittest.main()
