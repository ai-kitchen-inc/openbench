"""Tests for EPUB data source."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.data.exceptions import (
    ExtractionError,
    FileNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)
from openbench.data.sources.epub import EPUBSource

try:
    import ebooklib  # noqa: F401
    from ebooklib import epub  # noqa: F401

    import bs4  # noqa: F401

    _HAS_EPUB = True
except ImportError:
    _HAS_EPUB = False


def _make_epub(path: Path) -> None:
    """Write a minimal two-chapter EPUB to ``path``."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("id123")
    book.set_title("Test Book")
    book.set_language("en")

    c1 = epub.EpubHtml(title="One", file_name="c1.xhtml")
    c1.content = "<h1>Chapter One</h1><p>The quick brown fox.</p>"
    c2 = epub.EpubHtml(title="Two", file_name="c2.xhtml")
    c2.content = "<h1>Chapter Two</h1><p>Jumps over the lazy dog.</p>"
    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]
    epub.write_epub(str(path), book)


class TestEPUBSourceBasics(unittest.TestCase):
    """Init/properties require no optional dependency."""

    def test_source_type(self):
        source = EPUBSource(path="/path/to/book.epub")
        self.assertEqual(source.source_type, "epub")

    def test_source_id_format(self):
        source = EPUBSource(path="/path/to/book.epub")
        self.assertTrue(source.source_id.startswith("epub_"))
        self.assertEqual(len(source.source_id), 13)  # epub_ + 8 hex

    def test_source_id_stable(self):
        a = EPUBSource(path="/path/to/book.epub")
        b = EPUBSource(path="/path/to/book.epub")
        self.assertEqual(a.source_id, b.source_id)

    def test_validate_missing_path(self):
        source = EPUBSource(path="/does/not/exist.epub")
        with self.assertRaises(ValidationError):
            source.validate()

    def test_extract_missing_path_raises(self):
        source = EPUBSource(path="/does/not/exist.epub")
        with self.assertRaises(FileNotFoundError):
            source.extract()

    def test_extract_wrong_extension_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "notebook.txt"
            p.write_text("hi", encoding="utf-8")
            source = EPUBSource(path=p)
            with self.assertRaises(UnsupportedFormatError):
                source.extract()


@unittest.skipUnless(_HAS_EPUB, "ebooklib/beautifulsoup4 not installed")
class TestEPUBExtraction(unittest.TestCase):
    """Real extraction over a generated EPUB."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "book.epub"
        _make_epub(self.path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validate_ok(self):
        self.assertTrue(EPUBSource(path=self.path).validate())

    def test_extract_returns_chapter_text(self):
        raw = EPUBSource(path=self.path).extract()
        self.assertEqual(raw.content_type, "text")
        self.assertIn("quick brown fox", raw.content)
        self.assertIn("lazy dog", raw.content)
        # Two content chapters (nav is empty -> skipped).
        self.assertGreaterEqual(raw.metadata["chapter_count"], 2)
        self.assertEqual(raw.metadata["title"], "Test Book")


if __name__ == "__main__":
    unittest.main()
