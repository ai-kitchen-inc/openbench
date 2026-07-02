"""Tests for the fast-first General Chat document extractor."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat import extractor as extractor_mod  # noqa: E402
from general_chat.extractor import DoclingContentExtractor  # noqa: E402
from openbench.chat.files import StoredFile  # noqa: E402


def _stored(name: str, mime: str) -> StoredFile:
    return StoredFile(
        id="file-1",
        name=name,
        path=f"/tmp/{name}",
        mime_type=mime,
        size_bytes=10,
        stored_at="2026-01-01T00:00:00+00:00",
    )


class _FakeDoc:
    def __init__(self, markdown: str):
        self._markdown = markdown

    def export_to_markdown(self) -> str:
        return self._markdown


class _FakeResult:
    def __init__(self, markdown: str):
        self.document = _FakeDoc(markdown)


class _FakeConverter:
    def __init__(self, markdown: str):
        self._markdown = markdown
        self.calls = 0

    def convert(self, _path):
        self.calls += 1
        return _FakeResult(self._markdown)


class TestFastFirstExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = DoclingContentExtractor()

    def test_digital_pdf_uses_pypdf_and_never_calls_docling(self):
        with patch.object(DoclingContentExtractor, "_pdf_fast", return_value=("x" * 300, 2)), patch.object(
            extractor_mod, "_get_converter", side_effect=AssertionError("Docling should not run")
        ):
            text = self.extractor.extract(_stored("report.pdf", "application/pdf"))
        self.assertEqual(text, "x" * 300)

    def test_sparse_pdf_falls_back_to_docling_ocr(self):
        fake = _FakeConverter("OCR TEXT")
        with patch.object(DoclingContentExtractor, "_pdf_fast", return_value=("", 3)), patch.object(
            extractor_mod, "_get_converter", return_value=fake
        ):
            text = self.extractor.extract(_stored("scan.pdf", "application/pdf"))
        self.assertEqual(text.strip(), "OCR TEXT")
        self.assertEqual(fake.calls, 1)

    def test_docx_uses_python_docx_not_docling(self):
        with patch.object(
            DoclingContentExtractor, "_extract_with_python_docx", return_value="docx body text"
        ), patch.object(extractor_mod, "_get_converter", side_effect=AssertionError("no Docling")):
            text = self.extractor.extract(
                _stored(
                    "memo.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            )
        self.assertEqual(text, "docx body text")

    def test_converter_is_built_once(self):
        created = {"count": 0}

        class _CountingConverter:
            def __init__(self):
                created["count"] += 1

        fake_pkg = types.ModuleType("docling")
        fake_sub = types.ModuleType("docling.document_converter")
        fake_sub.DocumentConverter = _CountingConverter

        with patch.dict(sys.modules, {"docling": fake_pkg, "docling.document_converter": fake_sub}):
            with patch.object(extractor_mod, "_converter", None):
                first = extractor_mod._get_converter()
                second = extractor_mod._get_converter()
        self.assertIs(first, second)
        self.assertEqual(created["count"], 1)


if __name__ == "__main__":
    unittest.main()
