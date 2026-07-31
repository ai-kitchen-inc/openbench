"""Deleting a source must delete its chunks and Parquet files too.

Chunks and Parquet tables are copies of the user's uploaded data. If a
delete path misses them, content the user deleted stays retrievable and
keeps surfacing in answers, with no visible source to point at.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

EXAMPLE_SRC = Path(__file__).resolve().parent.parent / "examples" / "general-chat" / "src"
if str(EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_SRC))

try:
    from general_chat import source_index
    from general_chat.sources import SourceRecord

    HAS_GENERAL_CHAT = True
except ImportError:  # pragma: no cover - example deps not installed
    HAS_GENERAL_CHAT = False


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 16):
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for char in text.lower():
            vector[ord(char) % self.dimension] += 1.0
        return vector

    def embed(self, text: str, model: str | None = None) -> list[float]:
        return self._vector(text)

    def embed_batch(self, texts, model=None, batch_size=100):
        return [self._vector(text) for text in texts]

    def get_dimension(self, model: str | None = None) -> int:
        return self.dimension


@unittest.skipUnless(HAS_GENERAL_CHAT, "general-chat example is not importable")
class SourceIndexTestCase(unittest.TestCase):
    """Real SQLite index + catalog under a temp storage root."""

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
        os.environ["GENERAL_CHAT_TABLE_PARQUET_ENABLED"] = "1"
        os.environ["GENERAL_CHAT_STORAGE_ROOT"] = str(self.root)
        os.environ["GENERAL_CHAT_SOURCE_INDEX_MIN_CHARS"] = "10"
        os.environ.pop("OPENBENCH_DOC_INDEX_URL", None)
        os.environ.pop("GENERAL_CHAT_DATABASE_URL", None)

        source_index.reset_caches()
        index = source_index.get_document_index()
        # Force a deterministic offline embedder onto the real store.
        index._embedding_provider = FakeEmbeddingProvider()
        index._dimension = 16
        self.index = index
        self.catalog = source_index.get_table_catalog()

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        source_index.reset_caches()
        self._tmp.cleanup()

    def _record(self, source_id="source-1", session_id="s1", owner="alice@example.com"):
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


class TestIndexSourceRecord(SourceIndexTestCase):
    def test_indexing_records_metadata(self):
        record = source_index.index_source_record(self._record())
        self.assertEqual(record.metadata["indexStatus"], "ready")
        self.assertGreater(record.metadata["chunkCount"], 0)
        self.assertIn("summary", record.metadata)

    def test_indexed_text_is_searchable(self):
        source_index.index_source_record(self._record())
        from openbench.core.abstractions import Query

        result = self.index.search(
            Query(text="pendapatan", filters={"source_ids": ["source-1"]}, limit=3)
        )
        self.assertTrue(result.items)

    def test_short_text_is_skipped(self):
        record = self._record()
        record.text = "too short"
        indexed = source_index.index_source_record(record)
        self.assertEqual(indexed.metadata["indexStatus"], "skipped")

    def test_failed_record_is_skipped(self):
        record = self._record()
        record.status = "failed"
        indexed = source_index.index_source_record(record)
        self.assertEqual(indexed.metadata["indexStatus"], "skipped")

    def test_disabled_flag_leaves_metadata_untouched(self):
        os.environ["GENERAL_CHAT_SOURCE_INDEX_ENABLED"] = "0"
        source_index.reset_caches()
        record = source_index.index_source_record(self._record())
        self.assertNotIn("indexStatus", record.metadata or {})

    def test_indexing_failure_is_recorded_not_raised(self):
        class Broken:
            def index_text(self, *args, **kwargs):
                raise RuntimeError("embedding provider is down")

        source_index._document_index = Broken()
        record = source_index.index_source_record(self._record())
        self.assertEqual(record.metadata["indexStatus"], "failed")
        self.assertIn("down", record.metadata["indexError"])


class TestDeindexSource(SourceIndexTestCase):
    def setUp(self):
        super().setUp()
        self.record = source_index.index_source_record(self._record())

    def test_deindex_removes_chunks(self):
        self.assertGreater(self.index.stats(source_id="source-1")["chunks"], 0)
        source_index.deindex_source("source-1", owner="alice@example.com", session_id="s1")
        self.assertEqual(self.index.stats(source_id="source-1")["chunks"], 0)

    def test_deleted_source_is_not_searchable(self):
        source_index.deindex_source("source-1", owner="alice@example.com", session_id="s1")
        from openbench.core.abstractions import Query

        result = self.index.search(
            Query(text="pendapatan", filters={"source_ids": ["source-1"]}, limit=3)
        )
        self.assertEqual(result.items, [])

    def test_deindex_unknown_source_is_a_noop(self):
        source_index.deindex_source("source-missing")

    def test_deindex_records_uses_each_records_scope(self):
        source_index.deindex_records([self.record])
        self.assertEqual(self.index.stats(source_id="source-1")["chunks"], 0)

    def test_deindex_survives_an_unreachable_index(self):
        class Broken:
            def delete_source(self, source_id):
                raise RuntimeError("database is unreachable")

        source_index._document_index = Broken()
        # Must not raise: a delete route that fails here would leave the
        # user with content they cannot remove.
        source_index.deindex_source("source-1", owner="alice@example.com", session_id="s1")


@unittest.skipUnless(HAS_GENERAL_CHAT, "general-chat example is not importable")
class TestTabularIndexing(SourceIndexTestCase):
    def setUp(self):
        super().setUp()
        try:
            import pandas as pd
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pandas and pyarrow are not installed")

        self.csv = self.root / "sales.csv"
        pd.DataFrame({"region": ["North", "South", "North"], "amount": [100, 250, 50]}).to_csv(
            self.csv, index=False
        )

        class _Stored:
            def __init__(self, path):
                self.path = str(path)

        self.stored = _Stored(self.csv)

    def _tabular_record(self):
        record = SourceRecord.create(
            session_id="s1",
            name="sales.csv",
            kind="spreadsheet",
            mime_type="text/csv",
            size_bytes=64,
            text="### CSV: sales.csv",
            owner="alice@example.com",
        )
        record.id = "source-table"
        return record

    def test_parquet_is_written_outside_uploads(self):
        record = source_index.index_source_record(self._tabular_record(), stored_file=self.stored)
        self.assertEqual(record.metadata["indexStatus"], "ready")
        self.assertEqual(len(record.metadata["tables"]), 1)

        parquet_dir = source_index.table_root() / "alice_example_com" / "s1" / "source-table"
        self.assertTrue(parquet_dir.is_dir())
        self.assertTrue(list(parquet_dir.glob("*.parquet")))
        self.assertNotIn("uploads", str(source_index.table_root()))

    def test_catalog_row_is_created(self):
        source_index.index_source_record(self._tabular_record(), stored_file=self.stored)
        tables = self.catalog.list_for(source_ids=["source-table"])
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].row_count, 3)

    def test_schema_card_is_stored_for_the_prompt(self):
        record = source_index.index_source_record(self._tabular_record(), stored_file=self.stored)
        card = record.metadata["tables"][0]["schemaCard"]
        self.assertIn("region", card)
        self.assertIn("amount", card)

    def test_deindex_removes_parquet_and_catalog_rows(self):
        source_index.index_source_record(self._tabular_record(), stored_file=self.stored)
        parquet_dir = source_index.table_root() / "alice_example_com" / "s1" / "source-table"
        self.assertTrue(parquet_dir.is_dir())

        source_index.deindex_source("source-table", owner="alice@example.com", session_id="s1")
        self.assertFalse(parquet_dir.exists())
        self.assertEqual(self.catalog.list_for(source_ids=["source-table"]), [])

    def test_missing_local_file_does_not_fail_the_upload(self):
        class _Missing:
            path = str(self.root / "gone.csv")

        record = source_index.index_source_record(self._tabular_record(), stored_file=_Missing())
        self.assertNotEqual(record.metadata["indexStatus"], "failed")


@unittest.skipUnless(HAS_GENERAL_CHAT, "general-chat example is not importable")
class TestTurnEndCleanupDoesNotDeindex(unittest.TestCase):
    """Regression guard for the shared-helper trap.

    ``_delete_upload_files_for_records`` is called both by real deletes
    and by ``_cleanup_source_uploads_after_use`` at the end of every
    turn. Deindexing belongs only in ``_purge_source_artifacts``; if it
    ever moves into the shared helper, every source is wiped from the
    index as soon as the user asks a question about it.
    """

    def test_cleanup_helper_does_not_call_deindex(self):
        app_source = (EXAMPLE_SRC / "general_chat" / "server" / "app.py").read_text(
            encoding="utf-8"
        )

        cleanup_start = app_source.index("def _cleanup_source_uploads_after_use")
        cleanup_end = app_source.index("def render_items_fn", cleanup_start)
        cleanup_body = app_source[cleanup_start:cleanup_end]
        self.assertNotIn("deindex", cleanup_body)
        self.assertNotIn("_purge_source_artifacts", cleanup_body)

        delete_start = app_source.index("def _delete_upload_files_for_records")
        delete_end = app_source.index("def _purge_source_artifacts", delete_start)
        self.assertNotIn("deindex", app_source[delete_start:delete_end])

    def test_every_real_delete_route_purges(self):
        app_source = (EXAMPLE_SRC / "general_chat" / "server" / "app.py").read_text(
            encoding="utf-8"
        )
        for route in (
            'app.delete("/chat/sources/{thread_id}/{source_id}")',
            'app.delete("/chat/sources/{thread_id}")',
            'app.delete("/admin/shared-sources/{source_id}")',
            'app.delete("/sessions/{session_id}")',
        ):
            with self.subTest(route=route):
                start = app_source.index(route)
                body = app_source[start : start + 1400]
                self.assertIn("_purge_source_artifacts", body)


if __name__ == "__main__":
    unittest.main()
