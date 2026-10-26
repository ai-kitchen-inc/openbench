"""Tests for Google Cloud Storage file store integration."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from openbench.integrations.gcp import GCSFileStore


class FakeBlob:
    def __init__(self, bucket, name: str):
        self.bucket = bucket
        self.name = name
        self.metadata = {}
        self.content_type = None
        self.size = 0
        self.updated = datetime.now(timezone.utc)
        self._content = b""
        self.deleted = False

    def upload_from_string(self, content, content_type=None):
        if isinstance(content, str):
            content = content.encode("utf-8")
        self._content = bytes(content)
        self.content_type = content_type
        self.size = len(self._content)
        self.bucket.objects[self.name] = self

    def reload(self):
        if self.deleted:
            raise FileNotFoundError(self.name)

    def download_to_filename(self, filename: str):
        Path(filename).write_bytes(self._content)

    def delete(self):
        self.deleted = True
        self.bucket.objects.pop(self.name, None)

    def create_resumable_upload_session(self, **_kwargs):
        self.bucket.objects[self.name] = self
        return f"https://upload.example/{self.name}"


class FakeBucket:
    def __init__(self, name: str):
        self.name = name
        self.objects = {}

    def blob(self, name: str):
        blob = self.objects.get(name)
        if blob is None:
            blob = FakeBlob(self, name)
        return blob

    def list_blobs(self, prefix: str):
        return [blob for name, blob in self.objects.items() if name.startswith(prefix)]


class FakeClient:
    def __init__(self):
        self.buckets = {}

    def bucket(self, name: str):
        return self.buckets.setdefault(name, FakeBucket(name))


class TestGCSFileStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.store = GCSFileStore(
            "bucket",
            prefix="uploads",
            user_id="user/unsafe",
            session_id="thread-1",
            cache_root=self.tmp.name,
            client=self.client,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_get_download_delete_roundtrip(self):
        stored = self.store.store("../report.pdf", b"pdf bytes", "application/pdf")

        self.assertTrue(stored.id.startswith("file-"))
        self.assertEqual(stored.name, "report.pdf")
        self.assertEqual(stored.size_bytes, len(b"pdf bytes"))

        loaded = self.store.get(stored.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.name, "report.pdf")

        cache_path = self.store.get_local_path(stored.id)
        self.assertIsNotNone(cache_path)
        assert cache_path is not None
        self.assertEqual(Path(cache_path).read_bytes(), b"pdf bytes")

        self.assertTrue(self.store.delete(stored.id))
        self.assertIsNone(self.store.get(stored.id))

    def test_create_resumable_upload_session_uses_safe_object_name(self):
        upload = self.store.create_resumable_upload_session(
            filename="../big file.pdf",
            mime_type="application/pdf",
            size_bytes=100 * 1024 * 1024,
            session_id="thread/2",
        )

        self.assertTrue(upload.file_id.startswith("file-"))
        self.assertEqual(upload.bucket, "bucket")
        self.assertIn("/thread_2/", upload.object_name)
        self.assertTrue(upload.object_name.endswith("/big file.pdf"))
        self.assertEqual(upload.method, "PUT")
        self.assertEqual(upload.headers["Content-Type"], "application/pdf")

    def test_missing_file_returns_none(self):
        self.assertIsNone(self.store.get("file-missing"))
        self.assertIsNone(self.store.get_local_path("file-missing"))
        self.assertFalse(self.store.delete("file-missing"))


if __name__ == "__main__":
    unittest.main()
