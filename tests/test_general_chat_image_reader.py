"""Tests for the VLM-backed upload image reader and its Docling fallback."""

from __future__ import annotations

import sys
import types
import unittest
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat import extractor as extractor_mod  # noqa: E402
from general_chat import image_reader  # noqa: E402
from general_chat.extractor import DoclingContentExtractor  # noqa: E402
from general_chat.image_reader import (  # noqa: E402
    DETECTED_HEADING,
    SUMMARY_HEADING,
    VLMImageReader,
    get_image_reader,
    parse_read_response,
    reset_image_reader,
)

from openbench.chat.files import StoredFile  # noqa: E402

RESPONSE = (
    f"{DETECTED_HEADING}\nINVOICE 2026-10-27\nTotal: Rp 1.250.000\n\n"
    f"{SUMMARY_HEADING}\nA white page with five lines of black printed text."
)


class TestParseReadResponse(unittest.TestCase):
    def test_both_sections(self):
        ocr, summary = parse_read_response(RESPONSE)
        self.assertEqual(ocr, "INVOICE 2026-10-27\nTotal: Rp 1.250.000")
        self.assertEqual(summary, "A white page with five lines of black printed text.")

    def test_none_marker_means_no_text(self):
        ocr, summary = parse_read_response(
            f"{DETECTED_HEADING}\n(none)\n{SUMMARY_HEADING}\nA sunset."
        )
        self.assertEqual(ocr, "")
        self.assertEqual(summary, "A sunset.")

    def test_reordered_and_missing_headings(self):
        ocr, summary = parse_read_response(f"{SUMMARY_HEADING}\nA sign.\n{DETECTED_HEADING}\nSTOP")
        self.assertEqual((ocr, summary), ("STOP", "A sign."))
        self.assertEqual(parse_read_response("just text"), ("just text", ""))
        self.assertEqual(
            parse_read_response(f"{SUMMARY_HEADING}\nOnly summary"), ("", "Only summary")
        )
        self.assertEqual(parse_read_response(""), ("", ""))


class TestVLMImageReader(unittest.TestCase):
    def test_read_calls_provider_with_path_and_parses(self):
        provider = Mock()
        provider.provider_name = "gemini"
        provider.generate.return_value = SimpleNamespace(text=RESPONSE, model="gemini-2.5-flash")
        reader = VLMImageReader(provider, model="gemini-2.5-flash")
        result = reader.read("/tmp/x.jpg")
        provider.generate.assert_called_once()
        kwargs = provider.generate.call_args.kwargs
        self.assertEqual(kwargs["images"], ["/tmp/x.jpg"])
        self.assertEqual(kwargs["model"], "gemini-2.5-flash")
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertIn(DETECTED_HEADING, kwargs["prompt"])
        self.assertEqual(result.ocr_text, "INVOICE 2026-10-27\nTotal: Rp 1.250.000")
        self.assertTrue(result.description.startswith("A white page"))
        self.assertEqual(result.provider, "gemini")

    def test_provider_errors_propagate(self):
        provider = Mock()
        provider.generate.side_effect = RuntimeError("quota")
        with self.assertRaises(RuntimeError):
            VLMImageReader(provider, model="m").read("/tmp/x.jpg")


class TestGetImageReader(unittest.TestCase):
    def setUp(self):
        reset_image_reader()
        self.addCleanup(reset_image_reader)

    def test_docling_mode_disables_reader(self):
        with patch.dict(environ, {"GENERAL_CHAT_IMAGE_READER": "docling", "GOOGLE_API_KEY": "k"}):
            self.assertIsNone(get_image_reader())

    def test_no_provider_and_no_key_disables_reader(self):
        with (
            patch.dict(environ, {"GENERAL_CHAT_IMAGE_READER": "vlm"}),
            patch.object(image_reader, "_configured_provider", return_value=None),
        ):
            environ.pop("GOOGLE_API_KEY", None)
            environ.pop("GEMINI_API_KEY", None)
            self.assertIsNone(get_image_reader())

    def test_gemini_from_env_key_in_worker(self):
        with (
            patch.dict(
                environ, {"GOOGLE_API_KEY": "k", "GENERAL_CHAT_VLM_MODEL": "gemini-2.5-flash"}
            ),
            patch.object(image_reader, "_configured_provider", return_value=None),
        ):
            environ.pop("GENERAL_CHAT_IMAGE_READER", None)
            reader = get_image_reader()
        self.assertIsInstance(reader, VLMImageReader)
        self.assertEqual(reader.provider_name, "gemini")
        self.assertEqual(reader.model, "gemini-2.5-flash")
        # Cached per process.
        self.assertIs(get_image_reader(), reader)

    def test_configured_provider_wins(self):
        provider = Mock()
        provider.provider_name = "ollama"
        with (
            patch.dict(environ, {"GENERAL_CHAT_IMAGE_READER": "vlm"}),
            patch.object(image_reader, "_configured_provider", return_value=provider),
        ):
            reader = get_image_reader()
        self.assertIs(reader._provider, provider)


def _stored(name: str, mime: str) -> StoredFile:
    return StoredFile(
        id="file-1", name=name, path=f"/tmp/{name}", mime_type=mime, size_bytes=10, stored_at=""
    )


def _fake_docling(markdown: str) -> types.ModuleType:
    module = types.ModuleType("docling.document_converter")
    instance = Mock()
    instance.convert.return_value = SimpleNamespace(
        document=SimpleNamespace(export_to_markdown=Mock(return_value=markdown))
    )
    module.DocumentConverter = Mock(return_value=instance)
    return module


class TestExtractImageUsesReader(unittest.TestCase):
    def setUp(self):
        self.extractor = DoclingContentExtractor()

    def test_reader_result_used_and_docling_never_runs(self):
        reader = Mock()
        reader.read.return_value = image_reader.ImageReadResult(
            ocr_text="B 1234 XYZ",
            description="A car with a visible plate.",
            provider="gemini",
            model="gemini-2.5-flash",
        )
        with (
            patch.object(extractor_mod, "get_image_reader", return_value=reader),
            patch.object(
                extractor_mod, "_get_converter", side_effect=AssertionError("Docling must not run")
            ),
        ):
            payload = self.extractor.extract_image(_stored("car.jpg", "image/jpeg"))
        self.assertEqual(payload["ocr_text"], "B 1234 XYZ")
        self.assertIn("A car with a visible plate.", payload["description"])
        self.assertIn("JPEG image source car.jpg", payload["description"])
        self.assertIn("B 1234 XYZ", payload["search_text"])
        self.assertEqual(payload["metadata"]["reader"], "vlm")
        self.assertEqual(payload["metadata"]["readerModel"], "gemini-2.5-flash")

    def test_photo_without_text_is_still_readable(self):
        reader = Mock()
        reader.read.return_value = image_reader.ImageReadResult(
            ocr_text="", description="A beach at sunset.", provider="gemini", model="m"
        )
        with (
            patch.object(extractor_mod, "get_image_reader", return_value=reader),
            patch.object(extractor_mod, "_get_converter", side_effect=AssertionError("no Docling")),
        ):
            payload = self.extractor.extract_image(_stored("beach.png", "image/png"))
        self.assertEqual(payload["ocr_text"], "")
        self.assertIn("A beach at sunset.", payload["description"])
        self.assertIn("(No OCR text detected.)", payload["search_text"])

    def test_reader_failure_falls_back_to_docling(self):
        reader = Mock()
        reader.read.side_effect = RuntimeError("503 from Gemini")
        with (
            patch.object(extractor_mod, "get_image_reader", return_value=reader),
            patch.dict(sys.modules, {"docling.document_converter": _fake_docling("OCR TEXT")}),
            patch.object(extractor_mod, "_converter", None),
        ):
            payload = self.extractor.extract_image(_stored("scan.png", "image/png"))
        self.assertEqual(payload["ocr_text"], "OCR TEXT")
        self.assertEqual(payload["metadata"]["reader"], "docling")
        self.assertIn("with OCR-detected text", payload["description"])

    def test_no_reader_uses_docling(self):
        with (
            patch.object(extractor_mod, "get_image_reader", return_value=None),
            patch.dict(sys.modules, {"docling.document_converter": _fake_docling("Hello")}),
            patch.object(extractor_mod, "_converter", None),
        ):
            payload = self.extractor.extract_image(_stored("note.png", "image/png"))
        self.assertEqual(payload["ocr_text"], "Hello")
        self.assertEqual(payload["metadata"]["reader"], "docling")

    def test_empty_reader_answer_falls_back_then_raises_when_docling_empty_too(self):
        reader = Mock()
        reader.read.return_value = image_reader.ImageReadResult(
            ocr_text="", description="", provider="g", model="m"
        )
        with (
            patch.object(extractor_mod, "get_image_reader", return_value=reader),
            patch.dict(sys.modules, {"docling.document_converter": _fake_docling("")}),
            patch.object(extractor_mod, "_converter", None),
            self.assertRaisesRegex(ValueError, "No OCR text"),
        ):
            self.extractor.extract_image(_stored("blank.png", "image/png"))


if __name__ == "__main__":
    unittest.main()
