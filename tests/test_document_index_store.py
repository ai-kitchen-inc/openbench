"""Tests for DocumentIndexStore (SQLite backend + Postgres when available)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from openbench.core.abstractions import Query
from openbench.data.stores.document_index import (
    DocumentIndexStore,
    PgVectorBackend,
    SQLiteDocumentBackend,
    build_document_index,
)


class FakeEmbeddingProvider:
    """Deterministic embeddings: a bag-of-characters vector.

    Real semantics do not matter here; what matters is that identical
    text always yields an identical vector and that call counts are
    observable, so idempotency can be asserted.
    """

    def __init__(self, dimension: int = 32):
        self.dimension = dimension
        self.embed_calls = 0
        self.embedded_texts: list[str] = []

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for char in text.lower():
            vector[ord(char) % self.dimension] += 1.0
        return vector

    def embed(self, text: str, model: str | None = None) -> list[float]:
        self.embed_calls += 1
        self.embedded_texts.append(text)
        return self._vector(text)

    def embed_batch(
        self, texts: list[str], model: str | None = None, batch_size: int = 100
    ) -> list[list[float]]:
        self.embed_calls += len(texts)
        self.embedded_texts.extend(texts)
        return [self._vector(text) for text in texts]

    def get_dimension(self, model: str | None = None) -> int:
        return self.dimension


class SQLiteDocumentIndexTestCase(unittest.TestCase):
    """Shared fixture: a temp SQLite index with a fake embedder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.provider = FakeEmbeddingProvider()
        self.store = DocumentIndexStore(
            sqlite_path=self.root / "index.sqlite3",
            embedding_provider=self.provider,
            dimension=self.provider.dimension,
        )

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()


class TestIndexing(SQLiteDocumentIndexTestCase):
    def test_index_text_creates_chunks(self):
        text = "\n\n".join(
            f"Paragraph {i} about revenue growth and the operating margin "
            f"trend observed across the reporting period." * 3
            for i in range(20)
        )
        result = self.store.index_text(
            text, source_id="source-1", session_id="s1", owner="user@example.com", name="doc.md"
        )
        self.assertGreater(result["chunk_count"], 1)
        self.assertEqual(result["indexed"], result["chunk_count"])
        self.assertEqual(result["skipped"], 0)

    def test_empty_text_indexes_nothing(self):
        result = self.store.index_text("   ", source_id="source-empty", session_id="s1")
        self.assertEqual(result["chunk_count"], 0)
        self.assertEqual(result["indexed"], 0)
        self.assertEqual(self.provider.embed_calls, 0)

    def test_reindex_identical_content_issues_zero_embed_calls(self):
        text = "\n\n".join(f"Section {i} discusses operating costs." for i in range(15))
        self.store.index_text(text, source_id="source-1", session_id="s1")
        first_pass_calls = self.provider.embed_calls
        self.assertGreater(first_pass_calls, 0)

        self.store.index_text(text, source_id="source-1", session_id="s1")
        self.assertEqual(
            self.provider.embed_calls,
            first_pass_calls,
            "re-indexing unchanged content must not re-embed",
        )

    def test_reindex_shorter_document_drops_orphan_chunks(self):
        long_text = "\n\n".join(f"Chapter {i} body text here." for i in range(30))
        first = self.store.index_text(long_text, source_id="source-1", session_id="s1")

        short_text = "Only one paragraph now."
        second = self.store.index_text(short_text, source_id="source-1", session_id="s1")

        self.assertEqual(second["chunk_count"], 1)
        self.assertEqual(second["deleted"], first["chunk_count"] - 1)
        stats = self.store.stats(source_id="source-1")
        self.assertEqual(stats["chunks"], 1)

    def test_index_raw_data_requires_source_id(self):
        from openbench.core.abstractions import RawData
        from openbench.data.stores.exceptions import StoreError

        data = RawData(content="hello", content_type="text", metadata={})
        with self.assertRaises(StoreError):
            self.store.index(data)

    def test_index_raw_data_uses_metadata_source_id(self):
        from openbench.core.abstractions import RawData

        data = RawData(
            content="Revenue rose sharply in the third quarter.",
            content_type="text",
            metadata={"source_id": "source-raw", "session_id": "s1"},
        )
        self.assertEqual(self.store.index(data), "source-raw")
        self.assertEqual(self.store.stats(source_id="source-raw")["chunks"], 1)


class TestSearch(SQLiteDocumentIndexTestCase):
    def setUp(self):
        super().setUp()
        self.store.index_text(
            "\n\n".join(
                [
                    "The quarterly revenue summary is presented here.",
                    "Operating expenses grew by twelve percent.",
                    "A rare token zzyzx appears only in this paragraph.",
                ]
            ),
            source_id="source-a",
            session_id="s1",
            owner="alice@example.com",
            name="a.md",
        )
        self.store.index_text(
            "Completely unrelated content about gardening and soil.",
            source_id="source-b",
            session_id="s2",
            owner="bob@example.com",
            name="b.md",
        )

    def test_search_returns_result_item_shape(self):
        result = self.store.search(Query(text="revenue", limit=3))
        self.assertTrue(result.items)
        item = result.items[0]
        self.assertIn("id", item)
        self.assertIn("content", item)
        self.assertIn("metadata", item)
        self.assertIn("source_id", item["metadata"])
        self.assertEqual(len(result.scores), len(result.items))

    def test_source_ids_filter_scopes_results(self):
        result = self.store.search(
            Query(text="gardening", filters={"source_ids": ["source-a"]}, limit=5)
        )
        for item in result.items:
            self.assertEqual(item["metadata"]["source_id"], "source-a")

    def test_empty_source_ids_matches_nothing(self):
        result = self.store.search(Query(text="revenue", filters={"source_ids": []}, limit=5))
        self.assertEqual(result.items, [])
        self.assertEqual(result.total, 0)

    def test_owner_filter_isolates_users(self):
        result = self.store.search(
            Query(text="gardening soil", filters={"owner": "alice@example.com"}, limit=5)
        )
        for item in result.items:
            self.assertEqual(item["metadata"]["owner"], "alice@example.com")

    def test_unknown_source_id_returns_nothing(self):
        result = self.store.search(
            Query(text="revenue", filters={"source_ids": ["source-does-not-exist"]}, limit=5)
        )
        self.assertEqual(result.items, [])

    def test_exact_rare_term_ranks_first(self):
        result = self.store.search(Query(text="zzyzx", limit=5))
        self.assertTrue(result.items)
        self.assertIn("zzyzx", result.items[0]["content"])

    def test_rare_term_wins_against_a_wall_of_similar_chunks(self):
        """Keyword-only hits must not be buried by uniform vector scores.

        With many near-identical passages, every vector score is close to
        the maximum. If a keyword-only hit were scored 0 on the vector
        axis it could never surface, which is exactly the case hybrid
        search is supposed to cover.
        """
        filler = "\n\n".join(
            f"Bagian {i} membahas operasional gudang pada wilayah {i}." for i in range(60)
        )
        store = DocumentIndexStore(
            sqlite_path=self.root / "wall.sqlite3",
            embedding_provider=FakeEmbeddingProvider(),
            dimension=32,
        )
        try:
            store.index_text(
                filler + "\n\nMarjin laba bersih adalah dua belas koma empat persen.",
                source_id="source-wall",
                session_id="s1",
            )
            result = store.search(Query(text="marjin laba bersih", limit=5))
            joined = " ".join(item["content"] for item in result.items)
            self.assertIn("Marjin laba bersih", joined)
        finally:
            store.close()

    def test_search_respects_limit(self):
        result = self.store.search(Query(text="the", limit=2))
        self.assertLessEqual(len(result.items), 2)

    def test_empty_store_returns_empty_result(self):
        empty = DocumentIndexStore(
            sqlite_path=self.root / "empty.sqlite3",
            embedding_provider=FakeEmbeddingProvider(),
            dimension=32,
        )
        try:
            result = empty.search(Query(text="anything", limit=5))
            self.assertEqual(result.items, [])
            self.assertEqual(result.total, 0)
        finally:
            empty.close()


class TestReadAndOutline(SQLiteDocumentIndexTestCase):
    def setUp(self):
        super().setUp()
        self.text = "\n\n".join(
            [
                "# Introduction",
                "Body text for the introduction section goes here.",
                "# Methods",
                "Body text describing the methods used in the study.",
                "# Results",
                "Body text summarizing the results of the analysis.",
            ]
        )
        self.store.index_text(self.text, source_id="source-doc", session_id="s1", name="paper.md")

    def test_outline_lists_headings(self):
        outline = self.store.outline("source-doc")
        headings = [entry["heading"] for entry in outline]
        self.assertIn("Introduction", headings)
        for entry in outline:
            self.assertIsInstance(entry["chunk_index"], int)

    def test_read_range_is_ordered_and_clamped(self):
        chunks = self.store.read_range("source-doc", start_index=0, chunk_count=2)
        self.assertLessEqual(len(chunks), 2)
        indexes = [chunk["metadata"]["chunk_index"] for chunk in chunks]
        self.assertEqual(indexes, sorted(indexes))

    def test_read_range_negative_start_clamps_to_zero(self):
        chunks = self.store.read_range("source-doc", start_index=-10, chunk_count=1)
        if chunks:
            self.assertEqual(chunks[0]["metadata"]["chunk_index"], 0)

    def test_read_range_past_end_returns_empty(self):
        self.assertEqual(self.store.read_range("source-doc", start_index=9999), [])

    def test_summarize_source_truncates(self):
        summary = self.store.summarize_source("source-doc", max_chars=20)
        self.assertLessEqual(len(summary), 21)  # +1 for the ellipsis

    def test_summarize_unknown_source_is_empty(self):
        self.assertEqual(self.store.summarize_source("nope"), "")


class TestDeletion(SQLiteDocumentIndexTestCase):
    def setUp(self):
        super().setUp()
        self.store.index_text(
            "\n\n".join(f"Paragraph {i} of the report." for i in range(10)),
            source_id="source-del",
            session_id="s1",
        )

    def test_delete_source_removes_all_chunks(self):
        deleted = self.store.delete_source("source-del")
        self.assertGreater(deleted, 0)
        self.assertEqual(self.store.stats(source_id="source-del")["chunks"], 0)

    def test_deleted_source_is_not_searchable(self):
        self.store.delete_source("source-del")
        result = self.store.search(
            Query(text="report paragraph", filters={"source_ids": ["source-del"]}, limit=5)
        )
        self.assertEqual(result.items, [])

    def test_delete_unknown_source_is_noop(self):
        self.assertEqual(self.store.delete_source("source-missing"), 0)

    def test_delete_single_chunk(self):
        self.assertTrue(self.store.delete("source-del-chunk-0"))
        self.assertIsNone(self.store.get("source-del-chunk-0"))

    def test_delete_unknown_chunk_returns_false(self):
        self.assertFalse(self.store.delete("source-del-chunk-9999"))

    def test_update_replaces_content_and_reembeds(self):
        before = self.provider.embed_calls
        self.assertTrue(self.store.update("source-del-chunk-0", "Replacement body text."))
        self.assertGreater(self.provider.embed_calls, before)
        self.assertEqual(self.store.get("source-del-chunk-0")["content"], "Replacement body text.")

    def test_update_unknown_chunk_returns_false(self):
        self.assertFalse(self.store.update("source-del-chunk-9999", "x"))


class TestEmbeddingProviderResolution(unittest.TestCase):
    """The store must resolve provider AND dimension explicitly.

    ``EmbeddingMixin`` resolves with the model alone, which in a
    Google-only deployment silently produces an OpenAI provider, and
    never forwards the dimension — so a Google model would emit 3072-dim
    vectors into a 1536-dim column. Both would only fail in production.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved_key = os.environ.get("GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = "test-key-not-used"

    def tearDown(self):
        if self._saved_key is None:
            os.environ.pop("GOOGLE_API_KEY", None)
        else:
            os.environ["GOOGLE_API_KEY"] = self._saved_key
        self._tmp.cleanup()

    def _store(self, **kwargs):
        return DocumentIndexStore(sqlite_path=self.root / "resolve.sqlite3", **kwargs)

    def test_named_provider_is_honoured(self):
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider

        store = self._store(
            embedding_provider_name="google",
            embedding_model="gemini-embedding-001",
            dimension=1536,
        )
        try:
            self.assertIsInstance(store._get_embedding_provider(), GoogleEmbeddingProvider)
        finally:
            store.close()

    def test_requested_dimension_reaches_the_provider(self):
        store = self._store(
            embedding_provider_name="google",
            embedding_model="gemini-embedding-001",
            dimension=1536,
        )
        try:
            provider = store._get_embedding_provider()
            # Without the fix this returns the model default of 3072.
            self.assertEqual(provider.get_dimension(), 1536)
            self.assertEqual(store._get_dimension(), 1536)
        finally:
            store.close()

    def test_injected_provider_still_wins(self):
        provider = FakeEmbeddingProvider()
        store = self._store(embedding_provider=provider, embedding_provider_name="google")
        try:
            self.assertIs(store._get_embedding_provider(), provider)
        finally:
            store.close()

    def test_dimension_mismatch_raises_a_readable_error(self):
        from openbench.data.stores.exceptions import StoreError

        # Provider yields 32 dims; the index was configured for 1536.
        store = self._store(embedding_provider=FakeEmbeddingProvider(32), dimension=1536)
        try:
            with self.assertRaises(StoreError) as ctx:
                store.index_text("some text to index", source_id="s", session_id="s1")
            message = str(ctx.exception)
            self.assertIn("32", message)
            self.assertIn("1536", message)
        finally:
            store.close()

    def test_check_embeddings_reports_success(self):
        store = self._store(embedding_provider=FakeEmbeddingProvider(32), dimension=32)
        try:
            result = store.check_embeddings()
            self.assertTrue(result["ok"])
            self.assertEqual(result["actual_dimension"], 32)
            self.assertIsNone(result["error"])
        finally:
            store.close()

    def test_check_embeddings_reports_a_dimension_mismatch(self):
        store = self._store(embedding_provider=FakeEmbeddingProvider(32), dimension=1536)
        try:
            result = store.check_embeddings()
            self.assertFalse(result["ok"])
            self.assertIn("1536", result["error"])
        finally:
            store.close()

    def test_check_embeddings_reports_a_broken_provider(self):
        class Broken:
            def embed(self, text, model=None):
                raise RuntimeError("api key not valid")

            def embed_batch(self, texts, model=None, batch_size=100):
                raise RuntimeError("api key not valid")

            def get_dimension(self, model=None):
                return 1536

        store = self._store(embedding_provider=Broken(), dimension=1536)
        try:
            result = store.check_embeddings()
            self.assertFalse(result["ok"])
            self.assertIn("api key", result["error"])
        finally:
            store.close()


class TestBuildDocumentIndex(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved_url = os.environ.pop("OPENBENCH_DOC_INDEX_URL", None)

    def tearDown(self):
        if self._saved_url is not None:
            os.environ["OPENBENCH_DOC_INDEX_URL"] = self._saved_url
        self._tmp.cleanup()

    def test_returns_none_without_configuration(self):
        self.assertIsNone(build_document_index())

    def test_storage_root_builds_sqlite_backend(self):
        store = build_document_index(
            storage_root=self.root,
            embedding_provider=FakeEmbeddingProvider(),
            dimension=32,
        )
        self.assertIsNotNone(store)
        self.assertIsInstance(store.backend, SQLiteDocumentBackend)

    def test_database_url_builds_postgres_backend(self):
        store = build_document_index(
            database_url="postgresql://user:pass@localhost/db",
            embedding_provider=FakeEmbeddingProvider(),
            dimension=32,
        )
        self.assertIsInstance(store.backend, PgVectorBackend)

    def test_requires_a_backend(self):
        with self.assertRaises(ValueError):
            DocumentIndexStore()

    def test_rejects_unsafe_table_name(self):
        with self.assertRaises(ValueError):
            SQLiteDocumentBackend(self.root / "x.sqlite3", table_name="chunks; DROP TABLE users")


@unittest.skipUnless(
    os.getenv("OPENBENCH_TEST_PG_URL"),
    "set OPENBENCH_TEST_PG_URL to run Postgres document index tests",
)
class TestPostgresBackend(unittest.TestCase):
    """Round-trip against a real Postgres, with or without pgvector."""

    def setUp(self):
        self.provider = FakeEmbeddingProvider()
        self.table = "openbench_test_chunks"
        self.store = DocumentIndexStore(
            backend=PgVectorBackend(os.environ["OPENBENCH_TEST_PG_URL"], table_name=self.table),
            embedding_provider=self.provider,
            dimension=self.provider.dimension,
        )
        self.store.index_text(
            "\n\n".join(
                [
                    "Quarterly revenue summary for the group.",
                    "A rare token zzyzx appears only here.",
                ]
            ),
            source_id="pg-source-1",
            session_id="s1",
            owner="alice@example.com",
        )

    def tearDown(self):
        self.store.delete_source("pg-source-1")
        self.store.close()

    def test_search_round_trip(self):
        result = self.store.search(
            Query(text="revenue", filters={"source_ids": ["pg-source-1"]}, limit=3)
        )
        self.assertTrue(result.items)

    def test_reindex_is_idempotent(self):
        before = self.provider.embed_calls
        self.store.index_text(
            "\n\n".join(
                [
                    "Quarterly revenue summary for the group.",
                    "A rare token zzyzx appears only here.",
                ]
            ),
            source_id="pg-source-1",
            session_id="s1",
            owner="alice@example.com",
        )
        self.assertEqual(self.provider.embed_calls, before)

    def test_scope_isolation(self):
        result = self.store.search(
            Query(text="revenue", filters={"source_ids": ["pg-other"]}, limit=3)
        )
        self.assertEqual(result.items, [])


if __name__ == "__main__":
    unittest.main()
