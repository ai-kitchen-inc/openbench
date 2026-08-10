"""Tests for PineconeDocumentBackend (in-memory fake index)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from openbench.core.abstractions import Query
from openbench.data.stores.document_index import (
    ChunkRow,
    DocumentIndexStore,
    SQLiteDocumentBackend,
    build_document_index,
)
from openbench.data.stores.exceptions import StoreConnectionError, StoreError
from openbench.data.stores.pinecone_document import PineconeDocumentBackend


def _matches_filter(metadata: dict, filt: dict | None) -> bool:
    if not filt:
        return True
    if "$and" in filt:
        return all(_matches_filter(metadata, sub) for sub in filt["$and"])
    for key, condition in filt.items():
        value = metadata.get(key)
        if "$eq" in condition and value != condition["$eq"]:
            return False
        if "$in" in condition and value not in condition["$in"]:
            return False
    return True


class FakePineconeIndex:
    """In-memory stand-in for a Pinecone serverless index.

    Mimics the attribute-style responses of the real client and, like
    Pinecone, stores every numeric metadata value as a float — so the
    backend's int coercion is exercised for real.
    """

    def __init__(self):
        # namespace -> id -> (values, metadata)
        self.records: dict[str, dict[str, tuple[list[float], dict]]] = {}

    def _bucket(self, namespace: str | None) -> dict[str, tuple[list[float], dict]]:
        return self.records.setdefault(namespace or "", {})

    def upsert(self, vectors, namespace=None):
        bucket = self._bucket(namespace)
        for vector in vectors:
            metadata = {
                key: float(value)
                if isinstance(value, int) and not isinstance(value, bool)
                else value
                for key, value in dict(vector["metadata"]).items()
            }
            bucket[vector["id"]] = (list(vector["values"]), metadata)

    def query(self, vector, top_k, namespace=None, filter=None, include_metadata=True):
        def _dot(left, right):
            return sum(a * b for a, b in zip(left, right, strict=False))

        scored = [
            SimpleNamespace(id=vid, score=_dot(vector, values), metadata=dict(metadata))
            for vid, (values, metadata) in self._bucket(namespace).items()
            if _matches_filter(metadata, filter)
        ]
        scored.sort(key=lambda match: match.score, reverse=True)
        return SimpleNamespace(matches=scored[:top_k])

    def fetch(self, ids, namespace=None):
        bucket = self._bucket(namespace)
        vectors = {
            vid: SimpleNamespace(id=vid, values=bucket[vid][0], metadata=dict(bucket[vid][1]))
            for vid in ids
            if vid in bucket
        }
        return SimpleNamespace(vectors=vectors)

    def delete(self, ids=None, namespace=None, filter=None):
        bucket = self._bucket(namespace)
        if ids is not None:
            for vid in list(ids):
                bucket.pop(vid, None)
            return
        if filter is not None:
            for vid in [v for v, (_, md) in bucket.items() if _matches_filter(md, filter)]:
                bucket.pop(vid)

    def list_paginated(self, prefix=None, namespace=None, pagination_token=None, limit=None):
        ids = sorted(vid for vid in self._bucket(namespace) if not prefix or vid.startswith(prefix))
        return SimpleNamespace(vectors=[SimpleNamespace(id=vid) for vid in ids], pagination=None)

    def describe_index_stats(self):
        namespaces = {
            namespace: SimpleNamespace(vector_count=len(bucket))
            for namespace, bucket in self.records.items()
        }
        total = sum(len(bucket) for bucket in self.records.values())
        return SimpleNamespace(namespaces=namespaces, total_vector_count=total)


class FakeEmbeddingProvider:
    """Deterministic bag-of-characters embeddings (same idea as the SQLite tests)."""

    def __init__(self, dimension: int = 32):
        self.dimension = dimension
        self.embed_calls = 0

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for char in text.lower():
            vector[ord(char) % self.dimension] += 1.0
        return vector

    def embed(self, text: str, model: str | None = None) -> list[float]:
        self.embed_calls += 1
        return self._vector(text)

    def embed_batch(
        self, texts: list[str], model: str | None = None, batch_size: int = 100
    ) -> list[list[float]]:
        self.embed_calls += len(texts)
        return [self._vector(text) for text in texts]

    def get_dimension(self, model: str | None = None) -> int:
        return self.dimension


def _row(source_id: str, idx: int, total: int, content: str, **overrides) -> ChunkRow:
    defaults = {
        "chunk_id": f"{source_id}-chunk-{idx}",
        "source_id": source_id,
        "session_id": "s1",
        "owner": "user@example.com",
        "chunk_index": idx,
        "total_chunks": total,
        "content": content,
        "content_hash": f"hash-{idx}",
        "metadata": {"name": "doc.md", "kind": "upload", "url": ""},
    }
    defaults.update(overrides)
    return ChunkRow(**defaults)


class PineconeBackendTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakePineconeIndex()
        self.backend = PineconeDocumentBackend(index_name="test-index", index=self.fake)
        self.backend._read_retry_delay = 0.0
        self.backend.ensure_schema(32)


class TestBackendMethods(PineconeBackendTestCase):
    def _seed(self, source_id: str = "src-1", count: int = 3) -> None:
        rows = [
            _row(
                source_id,
                idx,
                count,
                f"# Section {idx}\nParagraph about topic {idx}.",
                heading=f"Section {idx}",
            )
            for idx in range(count)
        ]
        vectors = [[float(idx + 1)] * 32 for idx in range(count)]
        self.assertEqual(self.backend.upsert(rows, vectors), count)

    def test_upsert_and_get_chunk_round_trip(self):
        self._seed()
        chunk = self.backend.get_chunk("src-1-chunk-1")
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.source_id, "src-1")
        self.assertEqual(chunk.chunk_index, 1)
        self.assertEqual(chunk.total_chunks, 3)
        self.assertEqual(chunk.heading, "Section 1")
        self.assertEqual(chunk.metadata.get("name"), "doc.md")
        self.assertEqual(chunk.content, "# Section 1\nParagraph about topic 1.")

    def test_get_chunk_missing_returns_none(self):
        self.assertIsNone(self.backend.get_chunk("nope-chunk-0"))

    def test_existing_hashes(self):
        self._seed()
        self.assertEqual(
            self.backend.existing_hashes("src-1"),
            {0: "hash-0", 1: "hash-1", 2: "hash-2"},
        )
        self.assertEqual(self.backend.existing_hashes("unknown"), {})

    def test_delete_source(self):
        self._seed("src-1")
        self._seed("src-2")
        self.assertEqual(self.backend.delete_source("src-1"), 3)
        self.assertEqual(self.backend.existing_hashes("src-1"), {})
        self.assertEqual(len(self.backend.existing_hashes("src-2")), 3)

    def test_delete_chunk(self):
        self._seed()
        self.assertTrue(self.backend.delete_chunk("src-1-chunk-0"))
        self.assertFalse(self.backend.delete_chunk("src-1-chunk-0"))

    def test_delete_chunks_from(self):
        self._seed(count=4)
        self.assertEqual(self.backend.delete_chunks_from("src-1", 2), 2)
        self.assertEqual(sorted(self.backend.existing_hashes("src-1")), [0, 1])

    def test_vector_search_filters_by_source(self):
        self._seed("src-1")
        self._seed("src-2")
        hits = self.backend.vector_search([1.0] * 32, filters={"source_ids": ["src-1"]}, limit=10)
        self.assertTrue(hits)
        self.assertTrue(all(chunk.source_id == "src-1" for chunk, _ in hits))

    def test_vector_search_empty_scope_matches_nothing(self):
        self._seed()
        self.assertEqual(
            self.backend.vector_search([1.0] * 32, filters={"source_ids": []}, limit=10), []
        )

    def test_vector_search_owner_and_session_filters(self):
        self._seed()
        self.assertTrue(
            self.backend.vector_search(
                [1.0] * 32,
                filters={"owner": "user@example.com", "session_id": "s1"},
                limit=10,
            )
        )
        self.assertEqual(
            self.backend.vector_search([1.0] * 32, filters={"owner": "other"}, limit=10), []
        )

    def test_keyword_search_returns_nothing(self):
        self._seed()
        self.assertEqual(self.backend.keyword_search("topic", filters={}, limit=10), [])

    def test_read_range_ordered(self):
        self._seed(count=4)
        rows = self.backend.read_range("src-1", 1, 3)
        self.assertEqual([row.chunk_index for row in rows], [1, 2])

    def test_headings_ordered(self):
        self._seed(count=3)
        headings = self.backend.headings("src-1")
        self.assertEqual([row.heading for row in headings], ["Section 0", "Section 1", "Section 2"])

    def test_stats_scoped_and_unscoped(self):
        self._seed("src-1", count=3)
        self._seed("src-2", count=2)
        scoped = self.backend.stats(filters={"source_ids": ["src-1", "missing"]})
        self.assertEqual(scoped["chunks"], 3)
        self.assertEqual(scoped["sources"], 1)
        unscoped = self.backend.stats(filters={})
        self.assertEqual(unscoped["chunks"], 5)
        self.assertEqual(unscoped["sources"], -1)
        self.assertEqual(unscoped["backend"], "pinecone")

    def test_upsert_retries_rate_limit(self):
        calls = {"count": 0}
        original = self.fake.upsert

        def flaky_upsert(vectors, namespace=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("429 Too Many Requests")
            return original(vectors, namespace=namespace)

        with (
            mock.patch.object(self.fake, "upsert", side_effect=flaky_upsert),
            mock.patch("openbench.data.stores.pinecone_document.time.sleep"),
        ):
            self.backend.upsert([_row("src-r", 0, 1, "text")], [[1.0] * 32])
        self.assertEqual(calls["count"], 2)
        self.assertIsNotNone(self.backend.get_chunk("src-r-chunk-0"))

    def test_upsert_non_rate_error_raises(self):
        with (
            mock.patch.object(self.fake, "upsert", side_effect=RuntimeError("boom")),
            self.assertRaises(RuntimeError),
        ):
            self.backend.upsert([_row("src-e", 0, 1, "text")], [[1.0] * 32])

    def test_ensure_schema_without_key_raises(self):
        backend = PineconeDocumentBackend(index_name="test-index", api_key=None)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PINECONE_API_KEY", None)
            backend._api_key = None
            with self.assertRaises(StoreConnectionError):
                backend.ensure_schema(32)

    def test_uninitialized_backend_raises(self):
        backend = PineconeDocumentBackend(index_name="test-index", api_key="key")
        with self.assertRaises(StoreError):
            backend.get_chunk("any")


class TestFacadeOverPinecone(unittest.TestCase):
    """DocumentIndexStore behaviors that general-chat relies on."""

    def setUp(self):
        self.fake = FakePineconeIndex()
        backend = PineconeDocumentBackend(index_name="test-index", index=self.fake)
        backend._read_retry_delay = 0.0
        self.provider = FakeEmbeddingProvider()
        self.store = DocumentIndexStore(
            backend=backend,
            embedding_provider=self.provider,
            dimension=self.provider.dimension,
        )
        self.text = "\n\n".join(
            f"## Heading {i}\n" + f"Paragraph {i} about revenue growth and operating margins. " * 8
            for i in range(12)
        )

    def test_index_text_and_search(self):
        result = self.store.index_text(
            self.text, source_id="doc-1", session_id="s1", owner="user@example.com", name="doc.md"
        )
        self.assertGreater(result["chunk_count"], 1)
        self.assertEqual(result["indexed"], result["chunk_count"])

        hits = self.store.search(
            Query(text="revenue growth", filters={"source_ids": ["doc-1"]}, limit=3)
        )
        self.assertTrue(hits.items)
        self.assertEqual(hits.metadata["backend"], "pinecone")
        item = hits.items[0]
        self.assertEqual(item["metadata"]["source_id"], "doc-1")
        self.assertEqual(item["metadata"]["name"], "doc.md")
        self.assertIn("chunk_index", item["metadata"])

    def test_index_text_is_idempotent(self):
        self.store.index_text(self.text, source_id="doc-1", session_id="s1")
        calls_after_first = self.provider.embed_calls
        result = self.store.index_text(self.text, source_id="doc-1", session_id="s1")
        self.assertEqual(result["indexed"], 0)
        self.assertEqual(result["skipped"], result["chunk_count"])
        self.assertEqual(self.provider.embed_calls, calls_after_first)

    def test_reindex_shorter_trims_orphans(self):
        self.store.index_text(self.text, source_id="doc-1", session_id="s1")
        shorter = "## Heading 0\n" + "A single short paragraph."
        result = self.store.index_text(shorter, source_id="doc-1", session_id="s1")
        self.assertGreater(result["deleted"], 0)
        stats = self.store.stats(source_ids=["doc-1"])
        self.assertEqual(stats["chunks"], result["chunk_count"])

    def test_search_empty_scope_returns_nothing(self):
        self.store.index_text(self.text, source_id="doc-1", session_id="s1")
        hits = self.store.search(Query(text="revenue", filters={"source_ids": []}, limit=3))
        self.assertEqual(hits.items, [])

    def test_read_range_outline_summarize(self):
        self.store.index_text(self.text, source_id="doc-1", session_id="s1")
        chunks = self.store.read_range("doc-1", start_index=0, chunk_count=2)
        self.assertTrue(chunks)
        self.assertEqual(chunks[0]["metadata"]["chunk_index"], 0)

        outline = self.store.outline("doc-1")
        self.assertTrue(outline)
        self.assertIn("Heading", outline[0]["heading"])

        summary = self.store.summarize_source("doc-1")
        self.assertTrue(summary)

    def test_delete_source(self):
        self.store.index_text(self.text, source_id="doc-1", session_id="s1")
        deleted = self.store.delete_source("doc-1")
        self.assertGreater(deleted, 0)
        self.assertEqual(self.store.summarize_source("doc-1"), "")


class TestBuildDocumentIndexSelection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pinecone_selected_with_key(self):
        with mock.patch.dict(
            os.environ,
            {"PINECONE_API_KEY": "test-key", "PINECONE_DOC_INDEX": "my-chunks"},
        ):
            store = build_document_index(storage_root=self.root, vector_backend="pinecone")
        self.assertIsInstance(store.backend, PineconeDocumentBackend)
        self.assertEqual(store.backend.index_name, "my-chunks")

    def test_pinecone_without_key_falls_back(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PINECONE_API_KEY", None)
            os.environ.pop("OPENBENCH_DOC_INDEX_URL", None)
            with self.assertLogs("openbench.data.stores.document_index", level="WARNING"):
                store = build_document_index(storage_root=self.root, vector_backend="pinecone")
        self.assertIsInstance(store.backend, SQLiteDocumentBackend)

    def test_default_backend_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENBENCH_DOC_INDEX_URL", None)
            store = build_document_index(storage_root=self.root)
        self.assertIsInstance(store.backend, SQLiteDocumentBackend)


if __name__ == "__main__":
    unittest.main()
