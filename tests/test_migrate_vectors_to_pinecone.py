"""Tests for the pgvector -> Pinecone migration script (general-chat)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from openbench.data.stores.pinecone_document import PineconeDocumentBackend

try:
    from tests.test_pinecone_document_backend import FakePineconeIndex
except ImportError:  # unittest discover imports test modules top-level
    from test_pinecone_document_backend import FakePineconeIndex

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "general-chat"
    / "scripts"
    / "migrate_vectors_to_pinecone.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_vectors_to_pinecone", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _db_row(source_id: str, idx: int, total: int, *, embedding) -> tuple:
    return (
        f"{source_id}-chunk-{idx}",
        source_id,
        "s1",
        "user@example.com",
        idx,
        total,
        f"Content of chunk {idx}.",
        f"hash-{idx}",
        f"Heading {idx}" if idx == 0 else None,
        None,
        None,
        json.dumps({"name": "doc.md", "kind": "upload"}),
        embedding,
    )


class TestDecodeRow(unittest.TestCase):
    def test_decodes_pgvector_string_and_json_metadata(self):
        row, vector = script.decode_row(_db_row("src-1", 0, 2, embedding="[1,2,3]"))
        self.assertEqual(row.chunk_id, "src-1-chunk-0")
        self.assertEqual(row.source_id, "src-1")
        self.assertEqual(row.chunk_index, 0)
        self.assertEqual(row.total_chunks, 2)
        self.assertEqual(row.heading, "Heading 0")
        self.assertEqual(row.metadata, {"name": "doc.md", "kind": "upload"})
        self.assertEqual(vector, [1.0, 2.0, 3.0])

    def test_decodes_array_embedding_and_dict_metadata(self):
        db_row = list(_db_row("src-1", 1, 2, embedding=[0.5, 0.25]))
        db_row[11] = {"name": "doc.md"}
        row, vector = script.decode_row(tuple(db_row))
        self.assertEqual(row.metadata, {"name": "doc.md"})
        self.assertEqual(vector, [0.5, 0.25])


class TestMigrateBatches(unittest.TestCase):
    def _batches(self, source_id: str = "src-1", count: int = 5, batch_size: int = 2):
        decoded = [
            script.decode_row(_db_row(source_id, idx, count, embedding=[float(idx + 1)] * 4))
            for idx in range(count)
        ]
        for start in range(0, count, batch_size):
            chunk = decoded[start : start + batch_size]
            yield [row for row, _ in chunk], [vec for _, vec in chunk]

    def setUp(self):
        self.fake = FakePineconeIndex()
        self.backend = PineconeDocumentBackend(index_name="migrated", index=self.fake)
        self.backend._read_retry_delay = 0.0

    def test_migrates_all_chunks(self):
        result = script.migrate_batches(self.backend, self._batches())
        self.assertEqual(result["migrated"], 5)
        self.assertEqual(result["sources"], 1)
        self.assertEqual(result["dimension"], 4)
        chunk = self.backend.get_chunk("src-1-chunk-3")
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.content_hash, "hash-3")
        self.assertEqual(chunk.metadata.get("name"), "doc.md")

    def test_dry_run_writes_nothing(self):
        result = script.migrate_batches(self.backend, self._batches(), dry_run=True)
        self.assertEqual(result["migrated"], 5)
        self.assertEqual(self.fake.records, {})

    def test_verify_sample(self):
        result = script.migrate_batches(self.backend, self._batches())
        self.assertEqual(script.verify_sample(self.backend, result["sample"]), 0)
        tampered = [("src-1-chunk-0", "wrong-hash"), ("missing-chunk-9", "hash")]
        self.assertEqual(script.verify_sample(self.backend, tampered), 2)


if __name__ == "__main__":
    unittest.main()
