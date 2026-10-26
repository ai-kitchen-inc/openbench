"""Tests for AttachmentArchiver — date-partitioned forever-archive uploads."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from openbench.integrations.gcp.archive import AttachmentArchiver


class _FakeBlob:
    def __init__(self, name: str):
        self.name = name
        self.metadata: dict | None = None
        self.uploaded: tuple | None = None

    def upload_from_string(self, content, content_type=None):
        self.uploaded = (content, content_type)


class _FakeBucket:
    def __init__(self):
        self.blobs: list[_FakeBlob] = []

    def blob(self, name):
        blob = _FakeBlob(name)
        self.blobs.append(blob)
        return blob


class _FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket

    def bucket(self, _name):
        return self._bucket


class _ExplodingBucket:
    def blob(self, name):
        raise RuntimeError("boom")


class _ExplodingClient:
    def bucket(self, _name):
        return _ExplodingBucket()


class TestAttachmentArchiver(unittest.TestCase):
    def _archiver(self, client):
        return AttachmentArchiver("archive-bucket", prefix="archive", client=client)

    def test_archive_object_name_and_metadata(self):
        bucket = _FakeBucket()
        archiver = self._archiver(_FakeClient(bucket))

        uri = archiver.archive(
            "report.pdf",
            b"%PDF-1.4 data",
            "application/pdf",
            user_id="user-1",
            session_id="session-9",
        )

        self.assertEqual(len(bucket.blobs), 1)
        blob = bucket.blobs[0]
        # archive/<YYYY-MM-DD>/<file-xxxxxxxx>-report.pdf
        self.assertRegex(
            blob.name,
            r"^archive/\d{4}-\d{2}-\d{2}/file-[0-9a-f]{8}-report\.pdf$",
        )
        self.assertEqual(uri, f"gs://archive-bucket/{blob.name}")
        self.assertEqual(blob.uploaded, (b"%PDF-1.4 data", "application/pdf"))
        self.assertEqual(blob.metadata["openbench_original_name"], "report.pdf")
        self.assertEqual(blob.metadata["openbench_mime_type"], "application/pdf")
        self.assertEqual(blob.metadata["openbench_user_id"], "user-1")
        self.assertEqual(blob.metadata["openbench_session_id"], "session-9")
        self.assertTrue(blob.metadata["openbench_archived_at"])

    def test_archive_sanitizes_filename(self):
        bucket = _FakeBucket()
        archiver = self._archiver(_FakeClient(bucket))

        archiver.archive("../weird name!.txt", b"x", "text/plain")

        leaf = bucket.blobs[0].name.rsplit("/", 1)[-1]
        # path traversal stripped (Path(...).name), unsafe chars -> '_'
        self.assertNotIn("..", leaf)
        self.assertRegex(leaf, r"^file-[0-9a-f]{8}-weird_name_\.txt$")

    def test_archive_swallows_errors(self):
        archiver = self._archiver(_ExplodingClient())
        # Must never raise — best-effort contract.
        result = archiver.archive("x.txt", b"x", "text/plain")
        self.assertIsNone(result)

    def test_archive_defaults_user_and_session(self):
        bucket = _FakeBucket()
        archiver = self._archiver(_FakeClient(bucket))
        archiver.archive("a.txt", b"x", "text/plain")
        meta = bucket.blobs[0].metadata
        self.assertEqual(meta["openbench_user_id"], "default")
        self.assertEqual(meta["openbench_session_id"], "default")


class TestFromEnv(unittest.TestCase):
    def test_returns_none_when_bucket_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(AttachmentArchiver.from_env())

    def test_uses_archive_bucket_var_only(self):
        env = {
            "GENERAL_CHAT_ARCHIVE_BUCKET": "dedicated-archive",
            # uploads bucket must NOT be used as a fallback source
            "GENERAL_CHAT_GCP_BUCKET": "uploads-bucket",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            archiver = AttachmentArchiver.from_env()
        self.assertIsNotNone(archiver)
        self.assertEqual(archiver.bucket_name, "dedicated-archive")
        self.assertEqual(archiver.prefix, "archive")

    def test_custom_prefix(self):
        env = {
            "GENERAL_CHAT_ARCHIVE_BUCKET": "dedicated-archive",
            "GENERAL_CHAT_GCP_ARCHIVE_PREFIX": "permanent/files",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            archiver = AttachmentArchiver.from_env()
        self.assertEqual(archiver.prefix, "permanent/files")


if __name__ == "__main__":
    unittest.main()
