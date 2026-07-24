"""Tests for General Chat Google Drive link ingestion."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

import general_chat.google_drive as gd  # noqa: E402
from general_chat.google_drive import (  # noqa: E402
    EXPORT_FORMATS,
    DriveAccessError,
    DriveDownload,
    DriveLink,
    download_public_drive_file,
    drive_source_record,
    parse_drive_url,
)
from general_chat.sources import SourceParserRegistry  # noqa: E402
from openbench.chat.files import LocalFileStore  # noqa: E402

FILE_ID = "1AbCdEfGhIjKlMnOpQrStUv"


class TestParseDriveUrl(unittest.TestCase):
    def test_file_link_variants(self):
        for url in (
            f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
            f"https://drive.google.com/file/d/{FILE_ID}/preview",
            f"https://drive.google.com/file/d/{FILE_ID}/edit",
            f"https://www.drive.google.com/file/d/{FILE_ID}/view",
            f"https://drive.google.com/open?id={FILE_ID}",
            f"https://drive.google.com/uc?id={FILE_ID}&export=download",
            f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download",
        ):
            link = parse_drive_url(url)
            self.assertIsNotNone(link, url)
            self.assertEqual(link.file_id, FILE_ID, url)
            self.assertEqual(link.doc_kind, "file", url)

    def test_account_picker_segments(self):
        link = parse_drive_url(f"https://drive.google.com/u/1/file/d/{FILE_ID}/view")
        self.assertIsNotNone(link)
        self.assertEqual(link.file_id, FILE_ID)
        link = parse_drive_url(f"https://docs.google.com/document/u/0/d/{FILE_ID}/edit")
        self.assertIsNotNone(link)
        self.assertEqual(link.doc_kind, "document")

    def test_native_doc_kinds(self):
        cases = {
            f"https://docs.google.com/document/d/{FILE_ID}/edit": "document",
            f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit#gid=0": "spreadsheet",
            f"https://docs.google.com/presentation/d/{FILE_ID}/edit": "presentation",
        }
        for url, kind in cases.items():
            link = parse_drive_url(url)
            self.assertIsNotNone(link, url)
            self.assertEqual(link.doc_kind, kind, url)

    def test_resource_key_captured(self):
        link = parse_drive_url(
            f"https://drive.google.com/file/d/{FILE_ID}/view?resourcekey=0-abc123"
        )
        self.assertEqual(link.resource_key, "0-abc123")

    def test_non_google_hosts_fall_through(self):
        self.assertIsNone(parse_drive_url("https://example.com/file/d/abc/view"))
        self.assertIsNone(parse_drive_url("https://www.wikipedia.org"))

    def test_published_to_web_falls_through(self):
        self.assertIsNone(
            parse_drive_url(
                "https://docs.google.com/document/d/e/2PACX-longpublishid/pub"
            )
        )

    def test_unrecognized_google_paths_fall_through(self):
        self.assertIsNone(parse_drive_url("https://drive.google.com/drive/my-drive"))
        self.assertIsNone(parse_drive_url("https://docs.google.com/about"))

    def test_short_ids_rejected(self):
        self.assertIsNone(parse_drive_url("https://drive.google.com/file/d/short/view"))

    def test_folder_links_raise(self):
        for url in (
            f"https://drive.google.com/drive/folders/{FILE_ID}",
            f"https://drive.google.com/drive/u/0/folders/{FILE_ID}",
        ):
            with self.assertRaises(DriveAccessError) as ctx:
                parse_drive_url(url)
            self.assertFalse(ctx.exception.needs_auth)

    def test_forms_raise(self):
        with self.assertRaises(DriveAccessError):
            parse_drive_url(f"https://docs.google.com/forms/d/{FILE_ID}/viewform")

    def test_export_format_table(self):
        self.assertIn("format=docx", EXPORT_FORMATS["document"][0])
        self.assertIn("format=xlsx", EXPORT_FORMATS["spreadsheet"][0])
        self.assertIn("format=pptx", EXPORT_FORMATS["presentation"][0])


def _mock_response(
    *,
    status_code: int = 200,
    content_type: str = "text/plain",
    body: bytes = b"hello",
    headers: dict | None = None,
):
    response = Mock()
    response.status_code = status_code
    all_headers = {"content-type": content_type}
    all_headers.update(headers or {})
    response.headers = all_headers
    response.iter_content = lambda chunk_size: iter([body])
    response.raise_for_status = Mock()
    response.close = Mock()
    return response


def _file_link() -> DriveLink:
    return DriveLink(
        file_id=FILE_ID,
        doc_kind="file",
        resource_key=None,
        original_url=f"https://drive.google.com/file/d/{FILE_ID}/view",
    )


class TestDownloadPublicDriveFile(unittest.TestCase):
    def test_binary_success_with_content_disposition(self):
        response = _mock_response(
            content_type="application/pdf",
            body=b"%PDF-",
            headers={"content-disposition": 'attachment; filename="report.pdf"'},
        )
        with patch("requests.get", return_value=response) as mock_get:
            download = download_public_drive_file(_file_link(), max_bytes=1000)
        self.assertEqual(download.filename, "report.pdf")
        self.assertEqual(download.mime_type, "application/pdf")
        self.assertEqual(download.content, b"%PDF-")
        called_url = mock_get.call_args[0][0]
        self.assertIn(f"uc?export=download&id={FILE_ID}", called_url)

    def test_html_interstitial_needs_auth(self):
        response = _mock_response(content_type="text/html", body=b"<html>login</html>")
        with patch("requests.get", return_value=response):
            with self.assertRaises(DriveAccessError) as ctx:
                download_public_drive_file(_file_link(), max_bytes=1000)
        self.assertTrue(ctx.exception.needs_auth)

    def test_forbidden_status_needs_auth(self):
        response = _mock_response(status_code=403)
        with patch("requests.get", return_value=response):
            with self.assertRaises(DriveAccessError) as ctx:
                download_public_drive_file(_file_link(), max_bytes=1000)
        self.assertTrue(ctx.exception.needs_auth)

    def test_over_max_bytes(self):
        response = _mock_response(body=b"x" * 100)
        with patch("requests.get", return_value=response):
            with self.assertRaises(ValueError):
                download_public_drive_file(_file_link(), max_bytes=10)

    def test_native_doc_uses_export_url(self):
        link = DriveLink(
            file_id=FILE_ID,
            doc_kind="spreadsheet",
            resource_key=None,
            original_url=f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit",
        )
        response = _mock_response(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            body=b"PK",
        )
        with patch("requests.get", return_value=response) as mock_get:
            download = download_public_drive_file(link, max_bytes=1000)
        self.assertIn("/export?format=xlsx", mock_get.call_args[0][0])
        self.assertTrue(download.filename.endswith(".xlsx"))


class TestDriveSourceRecord(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file_store = LocalFileStore(upload_dir=self._tmp.name)
        stub_extractor = types.SimpleNamespace(extract=lambda stored_file: "")
        self.parser = SourceParserRegistry(document_extractor=stub_extractor)

    def test_public_success_produces_ready_record(self):
        download = DriveDownload(
            filename="notes.txt", content=b"drive says hi", mime_type="text/plain"
        )
        with patch.object(gd, "download_public_drive_file", return_value=download):
            record, stored = drive_source_record(
                session_id="s1",
                link=_file_link(),
                file_store=self.file_store,
                parser=self.parser,
                max_bytes=1000,
            )
        self.assertIsNotNone(stored)
        self.assertEqual(record.status, "ready")
        self.assertIn("drive says hi", record.text)
        self.assertEqual(record.metadata["driveFileId"], FILE_ID)
        self.assertEqual(record.metadata["driveAccess"], "public")
        self.assertTrue(record.url.startswith("/uploads/"))

    def test_needs_auth_failure_produces_failed_record(self):
        with patch.object(
            gd,
            "download_public_drive_file",
            side_effect=DriveAccessError(gd.MSG_NEEDS_AUTH, needs_auth=True),
        ):
            record, stored = drive_source_record(
                session_id="s1",
                link=_file_link(),
                file_store=self.file_store,
                parser=self.parser,
                max_bytes=1000,
            )
        self.assertIsNone(stored)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.kind, "url")
        self.assertEqual(record.error, gd.MSG_NEEDS_AUTH)
        self.assertEqual(record.url, _file_link().original_url)

    def test_credentialed_path_marks_oauth_access(self):
        download = DriveDownload(
            filename="private.txt", content=b"secret text", mime_type="text/plain"
        )
        with patch.object(
            gd, "download_drive_file_with_credentials", return_value=download
        ):
            record, stored = drive_source_record(
                session_id="s1",
                link=_file_link(),
                file_store=self.file_store,
                parser=self.parser,
                max_bytes=1000,
                credentials=object(),
            )
        self.assertIsNotNone(stored)
        self.assertEqual(record.metadata["driveAccess"], "oauth")

    def test_credentialed_failure_falls_back_to_public(self):
        download = DriveDownload(
            filename="public.txt", content=b"public text", mime_type="text/plain"
        )
        with (
            patch.object(
                gd,
                "download_drive_file_with_credentials",
                side_effect=DriveAccessError(gd.MSG_NO_ACCESS),
            ) as mock_api,
            patch.object(
                gd, "download_public_drive_file", return_value=download
            ) as mock_public,
        ):
            record, stored = drive_source_record(
                session_id="s1",
                link=_file_link(),
                file_store=self.file_store,
                parser=self.parser,
                max_bytes=1000,
                credentials=object(),
            )
        mock_api.assert_called_once()
        mock_public.assert_called_once()
        self.assertIsNotNone(stored)
        self.assertEqual(record.metadata["driveAccess"], "public")


if __name__ == "__main__":
    unittest.main()
