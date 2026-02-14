"""Tests for chat file storage and content extraction."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbench.chat.files import FileContentExtractor, FileStore, StoredFile
from openbench.chat.session import Attachment


class TestFileStore(unittest.TestCase):
    """Tests for FileStore."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = FileStore(upload_dir=self.tmpdir)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_and_get(self):
        """Round-trip: store a file and retrieve it."""
        content = b"Hello, world!"
        stored = self.store.store("test.txt", content, "text/plain")

        self.assertTrue(stored.id.startswith("file-"))
        self.assertEqual(stored.name, "test.txt")
        self.assertEqual(stored.mime_type, "text/plain")
        self.assertEqual(stored.size_bytes, len(content))
        self.assertTrue(Path(stored.path).exists())

        # Read back
        retrieved = self.store.get(stored.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test.txt")
        self.assertEqual(retrieved.size_bytes, len(content))

    def test_creates_directory(self):
        """FileStore.store() auto-creates upload_dir subdirectories."""
        nested_dir = os.path.join(self.tmpdir, "deep", "nested")
        store = FileStore(upload_dir=nested_dir)
        stored = store.store("file.txt", b"data", "text/plain")
        self.assertTrue(Path(stored.path).exists())

    def test_unique_ids(self):
        """Multiple stores should produce unique file IDs."""
        ids = set()
        for i in range(10):
            stored = self.store.store(f"file{i}.txt", b"data", "text/plain")
            ids.add(stored.id)
        self.assertEqual(len(ids), 10)

    def test_get_nonexistent(self):
        """get() returns None for unknown file ID."""
        result = self.store.get("file-nonexistent")
        self.assertIsNone(result)

    def test_strips_directory_traversal(self):
        """Filename with path separators should be sanitized."""
        stored = self.store.store("../../etc/passwd", b"data", "text/plain")
        self.assertEqual(stored.name, "passwd")

    def test_empty_directory_get(self):
        """get() returns None if file dir exists but is empty."""
        file_dir = Path(self.tmpdir) / "file-empty"
        file_dir.mkdir()
        result = self.store.get("file-empty")
        self.assertIsNone(result)


class TestStoredFile(unittest.TestCase):
    """Tests for StoredFile.to_attachment()."""

    def test_to_attachment(self):
        """to_attachment() produces correct Attachment."""
        stored = StoredFile(
            id="file-abc123",
            name="report.pdf",
            path="/tmp/uploads/file-abc123/report.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            stored_at="2026-01-01T00:00:00Z",
            extracted_text="Some extracted text",
        )
        att = stored.to_attachment(base_url="/uploads")

        self.assertIsInstance(att, Attachment)
        self.assertEqual(att.id, "file-abc123")
        self.assertEqual(att.name, "report.pdf")
        self.assertEqual(att.url, "/uploads/file-abc123/report.pdf")
        self.assertEqual(att.mime_type, "application/pdf")
        self.assertEqual(att.size_bytes, 2048)
        self.assertEqual(att.type, "file")
        self.assertEqual(att.extracted_text, "Some extracted text")

    def test_to_attachment_image_type(self):
        """Image MIME type produces type='image'."""
        stored = StoredFile(
            id="file-img1",
            name="photo.png",
            path="/tmp/photo.png",
            mime_type="image/png",
            size_bytes=1024,
            stored_at="2026-01-01T00:00:00Z",
        )
        att = stored.to_attachment(base_url="/uploads")
        self.assertEqual(att.type, "image")

    def test_to_attachment_audio_type(self):
        """Audio MIME type produces type='audio'."""
        stored = StoredFile(
            id="file-aud1",
            name="track.mp3",
            path="/tmp/track.mp3",
            mime_type="audio/mpeg",
            size_bytes=5000,
            stored_at="2026-01-01T00:00:00Z",
        )
        att = stored.to_attachment(base_url="/uploads")
        self.assertEqual(att.type, "audio")


class TestFileContentExtractor(unittest.TestCase):
    """Tests for FileContentExtractor."""

    def setUp(self):
        self.extractor = FileContentExtractor()

    def test_extract_text_file(self):
        """Text files are read directly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello from text file!")
            f.flush()
            stored = StoredFile(
                id="file-txt1",
                name="test.txt",
                path=f.name,
                mime_type="text/plain",
                size_bytes=20,
                stored_at="2026-01-01T00:00:00Z",
            )
            result = self.extractor.extract(stored)
            self.assertEqual(result, "Hello from text file!")

        os.unlink(f.name)

    def test_extract_image_metadata(self):
        """Image files return a metadata description."""
        stored = StoredFile(
            id="file-img1",
            name="photo.jpg",
            path="/tmp/photo.jpg",
            mime_type="image/jpeg",
            size_bytes=50000,
            stored_at="2026-01-01T00:00:00Z",
        )
        result = self.extractor.extract(stored)
        self.assertIn("Image: photo.jpg", result)
        self.assertIn("image/jpeg", result)
        self.assertIn("50000", result)

    def test_extract_unknown_type(self):
        """Unknown file types return a generic description."""
        stored = StoredFile(
            id="file-unk1",
            name="archive.zip",
            path="/tmp/archive.zip",
            mime_type="application/zip",
            size_bytes=100000,
            stored_at="2026-01-01T00:00:00Z",
        )
        result = self.extractor.extract(stored)
        self.assertIn("File: archive.zip", result)
        self.assertIn("application/zip", result)

    @patch("openbench.data.sources.pdf.PDFSource")
    def test_extract_pdf(self, mock_pdf_cls):
        """PDF files use PDFSource for extraction."""
        mock_raw_data = MagicMock()
        mock_raw_data.content = "Extracted PDF content here."
        mock_instance = MagicMock()
        mock_instance.extract.return_value = mock_raw_data
        mock_pdf_cls.return_value = mock_instance

        stored = StoredFile(
            id="file-pdf1",
            name="report.pdf",
            path="/tmp/report.pdf",
            mime_type="application/pdf",
            size_bytes=10000,
            stored_at="2026-01-01T00:00:00Z",
        )
        result = self.extractor.extract(stored)
        self.assertEqual(result, "Extracted PDF content here.")
        mock_pdf_cls.assert_called_once_with(path="/tmp/report.pdf")

    @patch("openbench.data.sources.pdf.PDFSource")
    def test_extract_pdf_failure(self, mock_pdf_cls):
        """PDF extraction failure returns error description."""
        mock_pdf_cls.return_value.extract.side_effect = RuntimeError("corrupt")

        stored = StoredFile(
            id="file-pdf2",
            name="bad.pdf",
            path="/tmp/bad.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            stored_at="2026-01-01T00:00:00Z",
        )
        result = self.extractor.extract(stored)
        self.assertIn("PDF: bad.pdf", result)
        self.assertIn("extraction failed", result)


class TestAttachmentExtractedText(unittest.TestCase):
    """Tests for Attachment.extracted_text field."""

    def test_to_dict_without_extracted_text(self):
        """Attachment without extracted_text omits the field."""
        att = Attachment(
            id="a1",
            type="file",
            name="f.txt",
            url="/f.txt",
            mime_type="text/plain",
        )
        d = att.to_dict()
        self.assertNotIn("extractedText", d)

    def test_to_dict_with_extracted_text(self):
        """Attachment with extracted_text includes the field."""
        att = Attachment(
            id="a1",
            type="file",
            name="f.txt",
            url="/f.txt",
            mime_type="text/plain",
            extracted_text="file content here",
        )
        d = att.to_dict()
        self.assertEqual(d["extractedText"], "file content here")

    def test_from_dict_with_extracted_text(self):
        """from_dict() preserves extractedText."""
        data = {
            "id": "a1",
            "type": "file",
            "name": "f.txt",
            "url": "/f.txt",
            "mimeType": "text/plain",
            "extractedText": "hello world",
        }
        att = Attachment.from_dict(data)
        self.assertEqual(att.extracted_text, "hello world")

    def test_from_dict_without_extracted_text(self):
        """from_dict() defaults extracted_text to None."""
        data = {
            "id": "a1",
            "type": "file",
            "name": "f.txt",
            "url": "/f.txt",
            "mimeType": "text/plain",
        }
        att = Attachment.from_dict(data)
        self.assertIsNone(att.extracted_text)


if __name__ == "__main__":
    unittest.main()
