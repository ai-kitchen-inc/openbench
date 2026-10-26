"""Re-embedding stored sources after an embedding model change.

Vectors made by the previous model no longer match new query vectors, so
the admin needs a way to rebuild them without re-uploading. The worker
must actually re-embed (the index's content-hash skip would otherwise
make it a no-op), the job must report progress, and the routes must be
admin-only and refuse to overlap.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

EXAMPLE_SRC = Path(__file__).resolve().parent.parent / "examples" / "general-chat" / "src"
if str(EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_SRC))

try:
    from general_chat import source_index
    from general_chat.server.source_reindex import SourceReindexJob, run_source_reindex
    from general_chat.sources import SourceRecord, SourceStore

    HAS_GENERAL_CHAT = True
except ImportError:  # pragma: no cover - example deps not installed
    HAS_GENERAL_CHAT = False

pytestmark = pytest.mark.integration


class FakeEmbeddingProvider:
    """Deterministic offline embedder that counts batch calls."""

    def __init__(self, dimension: int = 16):
        self.dimension = dimension
        self.batch_calls = 0

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for char in text.lower():
            vector[ord(char) % self.dimension] += 1.0
        return vector

    def embed(self, text: str, model: str | None = None) -> list[float]:
        return self._vector(text)

    def embed_batch(self, texts, model=None, batch_size=100):
        self.batch_calls += 1
        return [self._vector(text) for text in texts]

    def get_dimension(self, model: str | None = None) -> int:
        return self.dimension


@unittest.skipUnless(HAS_GENERAL_CHAT, "general-chat example is not importable")
class SourceIndexTestCase(unittest.TestCase):
    """Real SQLite index under a temp storage root, offline embedder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved_env = {
            key: os.environ.get(key)
            for key in (
                "GENERAL_CHAT_SOURCE_INDEX_ENABLED",
                "GENERAL_CHAT_TABLE_PARQUET_ENABLED",
                "GENERAL_CHAT_STORAGE_ROOT",
                "GENERAL_CHAT_SOURCE_INDEX_MIN_CHARS",
                "OPENBENCH_DOC_INDEX_URL",
                "GENERAL_CHAT_DATABASE_URL",
            )
        }
        os.environ["GENERAL_CHAT_SOURCE_INDEX_ENABLED"] = "1"
        os.environ["GENERAL_CHAT_TABLE_PARQUET_ENABLED"] = "0"
        os.environ["GENERAL_CHAT_STORAGE_ROOT"] = str(self.root)
        os.environ["GENERAL_CHAT_SOURCE_INDEX_MIN_CHARS"] = "10"
        os.environ.pop("OPENBENCH_DOC_INDEX_URL", None)
        os.environ.pop("GENERAL_CHAT_DATABASE_URL", None)

        source_index.reset_caches()
        self.provider = FakeEmbeddingProvider()
        index = source_index.get_document_index()
        index._embedding_provider = self.provider
        index._dimension = self.provider.dimension
        self.index = index

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        source_index.reset_caches()
        self._tmp.cleanup()

    def _record(self, source_id="source-1", session_id="global-sources", owner="shared"):
        record = SourceRecord.create(
            session_id=session_id,
            name="laporan.pdf",
            kind="document",
            mime_type="application/pdf",
            size_bytes=1024,
            text="Pendapatan naik dua belas persen tahun ini. " * 20,
            owner=owner,
        )
        record.id = source_id
        return record


class TestReindexSourceRecord(SourceIndexTestCase):
    def test_reindex_reembeds_unchanged_text(self):
        record = source_index.index_source_record(self._record())
        chunks_before = self.index.stats(source_id="source-1")["chunks"]
        calls_before = self.provider.batch_calls
        self.assertGreater(calls_before, 0)

        reindexed = source_index.reindex_source_record(record)

        # index_text alone would skip every chunk (same content hash).
        self.assertGreater(self.provider.batch_calls, calls_before)
        self.assertEqual(reindexed.metadata["indexStatus"], "ready")
        self.assertEqual(reindexed.metadata["chunkCount"], chunks_before)
        self.assertEqual(self.index.stats(source_id="source-1")["chunks"], chunks_before)
        self.assertIn("indexedAt", reindexed.metadata)

    def test_reindex_keeps_table_metadata(self):
        record = self._record()
        record.metadata = {"tables": [{"artifactId": "t1"}], "indexError": "old"}
        reindexed = source_index.reindex_source_record(record)
        self.assertEqual(reindexed.metadata["tables"], [{"artifactId": "t1"}])
        self.assertNotIn("indexError", reindexed.metadata)

    def test_short_text_is_skipped_unless_tables_exist(self):
        record = self._record()
        record.text = "too short"
        self.assertEqual(
            source_index.reindex_source_record(record).metadata["indexStatus"], "skipped"
        )
        with_tables = self._record(source_id="source-2")
        with_tables.text = "too short"
        with_tables.metadata = {"tables": [{"artifactId": "t1"}], "indexStatus": "ready"}
        self.assertEqual(
            source_index.reindex_source_record(with_tables).metadata["indexStatus"], "ready"
        )

    def test_not_ready_record_is_skipped(self):
        record = self._record()
        record.status = "failed"
        self.assertEqual(
            source_index.reindex_source_record(record).metadata["indexStatus"], "skipped"
        )

    def test_index_error_marks_failed(self):
        record = source_index.index_source_record(self._record())
        self.index.delete_source = Mock(side_effect=RuntimeError("db down"))
        reindexed = source_index.reindex_source_record(record)
        self.assertEqual(reindexed.metadata["indexStatus"], "failed")
        self.assertIn("db down", reindexed.metadata["indexError"])

    def test_disabled_index_is_skipped(self):
        os.environ["GENERAL_CHAT_SOURCE_INDEX_ENABLED"] = "0"
        self.assertEqual(
            source_index.reindex_source_record(self._record()).metadata["indexStatus"],
            "skipped",
        )


class TestRunSourceReindex(SourceIndexTestCase):
    def _store(self) -> SourceStore:
        return SourceStore(self.root / "store")

    def test_walks_every_target_and_reports_counts(self):
        store = self._store()
        shared = store.for_owner("shared")
        group = store.for_owner("group:g1")
        shared.add(self._record("s-1"))
        shared.add(self._record("s-2"))
        group.add(self._record("g-1", session_id="group-sources", owner="group:g1"))
        short = self._record("g-2", session_id="group-sources", owner="group:g1")
        short.text = "pendek"
        group.add(short)

        job = SourceReindexJob()
        asyncio.run(
            run_source_reindex(
                job,
                targets=[(shared, "global-sources"), (group, "group-sources")],
                semaphore=asyncio.Semaphore(2),
            )
        )

        self.assertEqual(job.status, "done")
        self.assertEqual((job.total, job.done, job.ready, job.skipped, job.failed), (4, 4, 3, 1, 0))
        self.assertTrue(job.finished_at)
        persisted = {r.id: r for r in shared.list("global-sources")}
        self.assertEqual(persisted["s-1"].metadata["indexStatus"], "ready")
        self.assertEqual(self.index.stats(source_id="g-1")["chunks"] > 0, True)

    def test_listing_failure_marks_job_failed(self):
        broken = Mock()
        broken.list.side_effect = RuntimeError("store offline")
        job = SourceReindexJob()
        asyncio.run(
            run_source_reindex(
                job, targets=[(broken, "global-sources")], semaphore=asyncio.Semaphore(1)
            )
        )
        self.assertEqual(job.status, "failed")
        self.assertIn("store offline", job.error)

    def test_start_refuses_overlap_and_cancel_stops_task(self):
        async def scenario():
            job = SourceReindexJob()
            release = asyncio.Event()

            async def wait_forever():
                await release.wait()

            self.assertTrue(job.start(wait_forever, embedding_model="m-1"))
            self.assertFalse(job.start(wait_forever))
            snapshot = job.snapshot()
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["embeddingModel"], "m-1")
            job.cancel()
            await asyncio.sleep(0)
            self.assertTrue(job._task.cancelled())

        asyncio.run(scenario())


@unittest.skipUnless(HAS_GENERAL_CHAT, "general-chat example is not importable")
class TestReindexEndpoints(unittest.TestCase):
    """Local-dev client (auth disabled → requester is admin by default)."""

    def _client(self, *, index_enabled: bool):
        from fastapi.testclient import TestClient

        stack = ExitStack()
        self.addCleanup(stack.close)
        self.addCleanup(source_index.set_vector_store, None)
        self.addCleanup(source_index.reset_caches)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                    "GENERAL_CHAT_SOURCE_INDEX_ENABLED": "1" if index_enabled else "0",
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        # The worker never gets to run under TestClient (no persistent
        # loop); the routes are what is under test here.
        self.worker = stack.enter_context(
            patch("general_chat.server.app.run_source_reindex", autospec=True)
        )
        from general_chat.server.app import create_app

        app = create_app()
        self.addCleanup(app.state.source_reindex_job.cancel)
        return TestClient(app)

    def test_get_reports_idle_snapshot(self):
        client = self._client(index_enabled=True)
        payload = client.get("/admin/sources/reindex").json()
        self.assertEqual(payload["status"], "idle")
        for key in ("total", "done", "ready", "failed", "skipped"):
            self.assertEqual(payload[key], 0)
        self.assertEqual(payload["embeddingModel"], "")

    def test_post_starts_job_and_refuses_overlap(self):
        client = self._client(index_enabled=True)
        response = client.post("/admin/sources/reindex")
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "running")
        self.assertTrue(payload["embeddingModel"])
        self.assertTrue(payload["startedAt"])
        self.worker.assert_called_once()

        again = client.post("/admin/sources/reindex")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(client.get("/admin/sources/reindex").json()["status"], "running")

    def test_post_rejected_when_index_disabled(self):
        client = self._client(index_enabled=False)
        response = client.post("/admin/sources/reindex")
        self.assertEqual(response.status_code, 400)
        self.assertIn("dinonaktifkan", response.json()["detail"])

    def test_user_role_is_blocked(self):
        client = self._client(index_enabled=True)
        headers = {"X-Local-Role": "user"}
        self.assertEqual(client.get("/admin/sources/reindex", headers=headers).status_code, 403)
        self.assertEqual(client.post("/admin/sources/reindex", headers=headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()
