"""Tests for General Chat GCP upload worker."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from openbench.chat.files import StoredFile

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.gcp_worker import GCSObjectEvent, process_gcs_object  # noqa: E402
from general_chat.sources import ParsedSourceContent, SourceRecord, SourceStore  # noqa: E402


class FakeParser:
    def __init__(self, text: str = "hello world " * 20, metadata=None):
        self.text = text
        self.metadata = metadata

    def parse_file(self, _stored_file):
        return ParsedSourceContent(text=self.text, metadata=self.metadata)


class FakeGCSFileStore:
    def __init__(self, tmpdir: str):
        self.tmpdir = Path(tmpdir)
        self.uploaded_text_objects = []
        self.stored = StoredFile(
            id="file-abc123",
            name="report.txt",
            path=str(self.tmpdir / "report.txt"),
            mime_type="text/plain",
            size_bytes=11,
            stored_at="2026-01-01T00:00:00+00:00",
            web_view_link="gs://bucket/uploads/default/thread-1/file-abc123/report.txt",
        )
        Path(self.stored.path).write_text("hello world", encoding="utf-8")

    def verify_uploaded_object(self, file_id: str):
        return self.stored if file_id == self.stored.id else None

    def get_by_object(self, object_name: str):
        # Mirrors GCSFileStore.get_by_object: resolve a StoredFile by exact
        # object name (the worker addresses blobs straight from the finalize
        # event instead of scanning list_blobs).
        if object_name and object_name in self.stored.web_view_link:
            return self.stored
        return None

    def get_local_path(self, file_id: str):
        return self.stored.path if file_id == self.stored.id else None

    def get_local_path_for_object(self, object_name: str, file_id: str):
        if file_id == self.stored.id and object_name in self.stored.web_view_link:
            return self.stored.path
        return None

    def object_name_for_derived(self, **_kwargs):
        return "derived/default/thread-1/file-abc123/extracted.md"

    def upload_text_object(self, **kwargs):
        self.uploaded_text_objects.append(kwargs)


class TestGeneralChatGCPWorker(unittest.TestCase):
    def test_process_gcs_object_is_idempotent_for_same_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SourceStore(tmpdir)
            record = SourceRecord.create(
                session_id="thread-1",
                name="report.txt",
                kind="file",
                mime_type="text/plain",
                size_bytes=11,
                url="gs://bucket/uploads/default/thread-1/file-abc123/report.txt",
                text="",
                status="processing",
                metadata={
                    "fileId": "file-abc123",
                    "gcsBucket": "bucket",
                    "gcsObject": "uploads/default/thread-1/file-abc123/report.txt",
                },
            )
            store.add(record)
            file_store = FakeGCSFileStore(tmpdir)
            event = GCSObjectEvent(
                bucket="bucket",
                object_name="uploads/default/thread-1/file-abc123/report.txt",
                generation="1",
            )

            first = process_gcs_object(
                event,
                source_store=store,
                file_store=file_store,
                source_parser=FakeParser(),
            )
            second = process_gcs_object(
                event,
                source_store=store,
                file_store=file_store,
                source_parser=FakeParser(),
            )

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None
            self.assertEqual(first.status, "ready")
            self.assertEqual(len(file_store.uploaded_text_objects), 1)
            updated = store.find_by_upload_file_id("file-abc123", session_id="thread-1")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.metadata.get("parseStatus"), "ready")
            self.assertEqual(updated.metadata.get("processedGeneration"), "1")

    def test_process_gcs_object_sanitizes_nul_bytes_before_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SourceStore(tmpdir)
            record = SourceRecord.create(
                session_id="thread-1",
                name="report.txt",
                kind="file",
                mime_type="text/plain",
                size_bytes=11,
                url="gs://bucket/uploads/default/thread-1/file-abc123/report.txt",
                text="",
                status="processing",
                metadata={
                    "fileId": "file-abc123",
                    "gcsBucket": "bucket",
                    "gcsObject": "uploads/default/thread-1/file-abc123/report.txt",
                },
            )
            store.add(record)
            file_store = FakeGCSFileStore(tmpdir)
            event = GCSObjectEvent(
                bucket="bucket",
                object_name="uploads/default/thread-1/file-abc123/report.txt",
                generation="1",
            )

            processed = process_gcs_object(
                event,
                source_store=store,
                file_store=file_store,
                source_parser=FakeParser(
                    text="hello\x00world",
                    metadata={"parserNote": "contains\x00nul"},
                ),
            )

            self.assertIsNotNone(processed)
            assert processed is not None
            self.assertEqual(processed.text, "hello\uFFFDworld")
            self.assertEqual(processed.metadata.get("parserNote"), "contains\uFFFDnul")
            self.assertEqual(file_store.uploaded_text_objects[0]["text"], "hello\uFFFDworld")
            updated = store.find_by_upload_file_id("file-abc123", session_id="thread-1")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertNotIn("\x00", updated.text)
            self.assertNotIn("\x00", updated.metadata.get("parserNote", ""))


if __name__ == "__main__":
    unittest.main()
