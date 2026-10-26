"""Tests for General Chat large upload helpers."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from openbench.chat.files import StoredFile

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.app import _read_upload_limited  # noqa: E402

pytestmark = pytest.mark.integration


class ChunkedUpload:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.read_calls = []

    async def read(self, size: int = -1):
        self.read_calls.append(size)
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class FakeGCSFileStore:
    def __init__(self, root: Path):
        self.root = root
        self.store_calls: list[tuple[str, bytes, str]] = []
        self.last_stored: StoredFile | None = None

    def store(self, filename: str, content: bytes, mime_type: str):
        self.store_calls.append((filename, content, mime_type))
        path = self.root / filename
        path.write_bytes(content)
        self.last_stored = StoredFile(
            id="file-small",
            name=filename,
            path=str(path),
            mime_type=mime_type,
            size_bytes=len(content),
            stored_at="2026-06-11T00:00:00+00:00",
            web_view_link=(f"gs://test-bucket/uploads/default/session-1/file-small/{filename}"),
        )
        return self.last_stored

    def verify_uploaded_object(self, file_id: str):
        if self.last_stored is not None and self.last_stored.id == file_id:
            return self.last_stored
        return None


class FakeStorageBackend:
    def __init__(self, file_store: FakeGCSFileStore):
        self._file_store = file_store

    def file_store(self):
        return self._file_store

    def session_store(self):
        return SimpleNamespace(load=lambda _id: None, save=lambda _session: None)

    def memory_store(self):
        return None


class TestGeneralChatGCPUploadAPI(unittest.TestCase):
    def test_read_upload_limited_reads_in_chunks(self):
        upload = ChunkedUpload([b"a" * 3, b"b" * 2])

        content = asyncio.run(_read_upload_limited(upload, 10))

        self.assertEqual(content, b"aaabb")
        self.assertEqual(upload.read_calls, [1024 * 1024, 1024 * 1024, 1024 * 1024])

    def test_read_upload_limited_rejects_oversized_without_finishing_stream(self):
        upload = ChunkedUpload([b"a" * 3, b"b" * 3, b"c" * 3])

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_read_upload_limited(upload, 5))

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertEqual(len(upload.read_calls), 2)

    def test_gcp_multipart_upload_queues_processing_without_inline_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            fake_file_store = FakeGCSFileStore(tmpdir)
            fake_storage = FakeStorageBackend(fake_file_store)
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = None
            agent._skill_registry = None

            with ExitStack() as stack:
                stack.enter_context(
                    patch.dict(
                        environ,
                        {
                            "GENERAL_CHAT_GCP_BUCKET": "test-bucket",
                            "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                            "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                            "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                            "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                        },
                        clear=False,
                    )
                )
                stack.enter_context(
                    patch("general_chat.server.app.create_agent", return_value=agent)
                )
                stack.enter_context(
                    patch(
                        "general_chat.server.app._build_storage_backend", return_value=fake_storage
                    )
                )
                parser = stack.enter_context(
                    patch(
                        "general_chat.server.app.source_record_from_file",
                        side_effect=AssertionError("multipart GCP upload parsed inline"),
                    )
                )
                from general_chat.server.app import create_app

                client = TestClient(create_app())
                response = client.post(
                    "/chat/upload",
                    files={"file": ("notes.txt", b"hello", "text/plain")},
                    data={"sessionId": "session-1"},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "processing")
                self.assertEqual(payload["metadata"]["fileId"], "file-small")
                self.assertEqual(payload["metadata"]["parseStatus"], "queued")
                self.assertEqual(
                    fake_file_store.store_calls, [("notes.txt", b"hello", "text/plain")]
                )
                parser.assert_not_called()

                status_response = client.get("/chat/uploads/file-small?sessionId=session-1")
                self.assertEqual(status_response.status_code, 200)
                status_payload = status_response.json()
                self.assertEqual(status_payload["fileId"], "file-small")
                self.assertEqual(status_payload["status"], "queued")
                self.assertEqual(status_payload["source"]["status"], "processing")
                self.assertNotIn("extractedText", status_payload["source"])

    def test_direct_upload_complete_does_not_regress_ready_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            fake_file_store = FakeGCSFileStore(tmpdir)
            fake_storage = FakeStorageBackend(fake_file_store)
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = None
            agent._skill_registry = None

            with ExitStack() as stack:
                stack.enter_context(
                    patch.dict(
                        environ,
                        {
                            "GENERAL_CHAT_GCP_BUCKET": "test-bucket",
                            "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                            "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                            "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                            "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                        },
                        clear=False,
                    )
                )
                stack.enter_context(
                    patch("general_chat.server.app.create_agent", return_value=agent)
                )
                stack.enter_context(
                    patch(
                        "general_chat.server.app._build_storage_backend", return_value=fake_storage
                    )
                )
                stack.enter_context(
                    patch(
                        "general_chat.server.app.source_record_from_file",
                        side_effect=AssertionError("multipart GCP upload parsed inline"),
                    )
                )
                from general_chat.server.app import create_app
                from general_chat.sources import build_source_store

                client = TestClient(create_app())
                upload_response = client.post(
                    "/chat/upload",
                    files={"file": ("notes.txt", b"hello", "text/plain")},
                    data={"sessionId": "session-1"},
                )
                self.assertEqual(upload_response.status_code, 200)

                source_store = build_source_store(tmpdir / "storage")
                record = source_store.find_by_upload_file_id("file-small", session_id="session-1")
                self.assertIsNotNone(record)
                assert record is not None
                record.status = "ready"
                record.text = "parsed text"
                metadata = dict(record.metadata or {})
                metadata["parseStatus"] = "ready"
                metadata["processedGeneration"] = "1"
                record.metadata = metadata
                source_store.upsert(record)

                complete_response = client.post(
                    "/chat/uploads/complete",
                    json={"fileId": "file-small", "sessionId": "session-1"},
                )

                self.assertEqual(complete_response.status_code, 200)
                payload = complete_response.json()
                self.assertEqual(payload["status"], "ready")
                self.assertEqual(payload["source"]["status"], "ready")
                self.assertNotIn("extractedText", payload["source"])
                text_status_response = client.get(
                    "/chat/uploads/file-small?sessionId=session-1&includeText=true"
                )
                self.assertEqual(text_status_response.status_code, 200)
                text_status_payload = text_status_response.json()
                self.assertEqual(text_status_payload["source"]["extractedText"], "parsed text")
                updated = source_store.find_by_upload_file_id("file-small", session_id="session-1")
                self.assertIsNotNone(updated)
                assert updated is not None
                self.assertEqual(updated.status, "ready")
                self.assertEqual(updated.metadata.get("parseStatus"), "ready")


if __name__ == "__main__":
    unittest.main()
