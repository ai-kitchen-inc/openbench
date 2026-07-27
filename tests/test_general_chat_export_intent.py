"""Tests for the bilingual export-intent detector used by General Chat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_EXAMPLE_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(_EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_SRC))

from general_chat.server.export_intent import (  # noqa: E402
    EXPORT_TOOL_BY_FORMAT,
    detect_export_intent,
)


class TestDetectExportIntentEnglish(unittest.TestCase):
    def test_excel_phrasings(self):
        for text in (
            "export this to excel",
            "can you download it as xlsx?",
            "save as an excel file please",
            "send me a spreadsheet of the results",
            "generate an excel workbook",
        ):
            with self.subTest(text=text):
                intent = detect_export_intent(text)
                self.assertIsNotNone(intent, text)
                assert intent is not None
                self.assertEqual(intent.format, "xlsx")
                self.assertEqual(intent.tool, "export_to_excel")

    def test_pdf_and_markdown(self):
        cases = {
            "export the summary as a pdf": ("pdf", "generate_pdf"),
            "save this as a markdown file": ("md", "generate_markdown"),
            "download it as .md": ("md", "generate_markdown"),
        }
        for text, (fmt, tool) in cases.items():
            with self.subTest(text=text):
                intent = detect_export_intent(text)
                self.assertIsNotNone(intent, text)
                assert intent is not None
                self.assertEqual(intent.format, fmt)
                self.assertEqual(intent.tool, tool)

    def test_pdf_merge_and_split(self):
        merge = detect_export_intent("please merge these pdf files")
        self.assertIsNotNone(merge)
        assert merge is not None
        self.assertEqual(merge.format, "pdf_merge")
        self.assertEqual(merge.tool, "merge_pdfs")

        split = detect_export_intent("split the pdf and give me pages 2 and 3")
        self.assertIsNotNone(split)
        assert split is not None
        self.assertEqual(split.format, "pdf_split")
        self.assertEqual(split.tool, "split_pdf")


class TestDetectExportIntentIndonesian(unittest.TestCase):
    def test_excel_phrasings(self):
        for text in (
            "tolong ekspor ke excel",
            "buatkan file excel dari data ini",
            "unduh sebagai xlsx dong",
            "bikin lembar kerja excel",
            "simpan sebagai file excel",
        ):
            with self.subTest(text=text):
                intent = detect_export_intent(text)
                self.assertIsNotNone(intent, text)
                assert intent is not None
                self.assertEqual(intent.format, "xlsx")
                self.assertEqual(intent.tool, "export_to_excel")

    def test_pdf_and_markdown(self):
        cases = {
            "unduh sebagai pdf": ("pdf", "generate_pdf"),
            "kirimkan berkas pdf laporannya": ("pdf", "generate_pdf"),
            "simpan sebagai markdown": ("md", "generate_markdown"),
        }
        for text, (fmt, tool) in cases.items():
            with self.subTest(text=text):
                intent = detect_export_intent(text)
                self.assertIsNotNone(intent, text)
                assert intent is not None
                self.assertEqual(intent.format, fmt)
                self.assertEqual(intent.tool, tool)

    def test_gabungkan_pdf_is_merge(self):
        intent = detect_export_intent("gabungkan pdf ini jadi satu")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.format, "pdf_merge")

    def test_file_request_without_named_format(self):
        intent = detect_export_intent("tolong unduh hasilnya sebagai berkas")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.format, "unknown")
        self.assertIsNone(intent.tool)


class TestDetectExportIntentNegatives(unittest.TestCase):
    def test_generic_requests_do_not_fire(self):
        for text in (
            "buatkan laporan penjualan",
            "tampilkan tabel penjualan",
            "summarize this document",
            "what is in the knowledge base?",
            "make me a chart",
            "",
            None,
        ):
            with self.subTest(text=text):
                self.assertIsNone(detect_export_intent(text))

    def test_trade_export_does_not_fire(self):
        # "ekspor" is also the Indonesian word for trade exports — a verb
        # alone must never be enough.
        self.assertIsNone(detect_export_intent("jelaskan tren ekspor impor Indonesia"))

    def test_word_boundaries(self):
        # 'md' inside 'admin' and 'xls' inside a longer token must not match.
        self.assertIsNone(detect_export_intent("download the admin guide"))
        self.assertIsNone(detect_export_intent("buka halaman admin"))


class TestMultiFormatRequests(unittest.TestCase):
    """One turn often asks for several files at once."""

    def test_english_three_formats(self):
        intent = detect_export_intent("export this to excel, pdf and markdown")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(set(intent.formats), {"pdf", "xlsx", "md"})
        self.assertEqual(
            set(intent.tools),
            {"generate_pdf", "export_to_excel", "generate_markdown"},
        )

    def test_indonesian_three_formats(self):
        intent = detect_export_intent("buatkan file excel, pdf, dan markdown")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(set(intent.formats), {"pdf", "xlsx", "md"})

    def test_two_formats(self):
        intent = detect_export_intent("unduh sebagai pdf dan excel")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(set(intent.formats), {"pdf", "xlsx"})

    def test_single_format_still_reports_one(self):
        intent = detect_export_intent("ekspor ke excel")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.formats, ("xlsx",))
        self.assertEqual(intent.tools, ("export_to_excel",))
        # `format`/`tool` stay the primary, for callers that want one.
        self.assertEqual(intent.format, "xlsx")
        self.assertEqual(intent.tool, "export_to_excel")

    def test_unknown_format_has_no_tools(self):
        intent = detect_export_intent("tolong unduh hasilnya sebagai berkas")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.format, "unknown")
        self.assertEqual(intent.tools, ())


class TestExportToolMap(unittest.TestCase):
    def test_every_format_maps_to_a_tool(self):
        for fmt, tool in EXPORT_TOOL_BY_FORMAT.items():
            self.assertTrue(tool, fmt)


if __name__ == "__main__":
    unittest.main()
