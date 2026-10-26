"""Tests for GCSFileStore object-name lookups (no list_blobs scan)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.integrations.gcp.file_store import GCSFileStore

_OBJECT = "uploads/default/session-1/file-abc123/doc.pdf"


class _FakeBlob:
    def __init__(self, name: str):
        self.name = name
        self.metadata = {
            "openbench_file_id": "file-abc123",
            "openbench_original_name": "doc.pdf",
            "openbench_mime_type": "application/pdf",
        }
        self.size = 1234
        self.updated = None
        self.content_type = "application/pdf"

    def reload(self):
        return None

    def download_to_filename(self, path):
        Path(path).write_bytes(b"%PDF-1.4 fake")


class _FakeBucket:
    def __init__(self):
        self.list_blobs_calls = 0

    def blob(self, name):
        return _FakeBlob(name)

    def list_blobs(self, *args, **kwargs):  # pragma: no cover - must not run
        self.list_blobs_calls += 1
        raise AssertionError("list_blobs must not be called for object-name lookups")


class _FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket

    def bucket(self, _name):
        return self._bucket


class TestGCSObjectLookup(unittest.TestCase):
    def _store(self):
        self.bucket = _FakeBucket()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return GCSFileStore(
            "test-bucket",
            prefix="uploads",
            client=_FakeClient(self.bucket),
            cache_root=self.tmp.name,
        )

    def test_get_by_object_no_scan(self):
        store = self._store()
        stored = store.get_by_object(_OBJECT)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.id, "file-abc123")
        self.assertEqual(stored.name, "doc.pdf")
        self.assertEqual(self.bucket.list_blobs_calls, 0)

    def test_get_local_path_for_object_downloads_without_scan(self):
        store = self._store()
        path = store.get_local_path_for_object(_OBJECT, "file-abc123")
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).exists())
        self.assertEqual(self.bucket.list_blobs_calls, 0)

    def test_get_local_path_for_object_requires_both_args(self):
        store = self._store()
        self.assertIsNone(store.get_local_path_for_object("", "file-x"))
        self.assertIsNone(store.get_local_path_for_object(_OBJECT, ""))


if __name__ == "__main__":
    unittest.main()
