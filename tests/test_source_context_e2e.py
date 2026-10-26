"""End-to-end: a huge document and a large CSV must not flood the prompt.

Exercises the real pipeline — index, Parquet conversion, card building,
retrieval, and the bound skills — with only the embedding provider faked.
This is the test that would have failed before the rework: a 500k-char
document and a 50k-row CSV used to be pushed into every turn.
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
    from general_chat.server.source_context import (
        build_source_attachments,
        current_source_scope,
        set_source_scope,
    )
    from general_chat.sources import SourceRecord

    HAS_GENERAL_CHAT = True
except ImportError:  # pragma: no cover - example deps not installed
    HAS_GENERAL_CHAT = False

try:
    import duckdb  # noqa: F401
    import pandas as pd
    import pyarrow  # noqa: F401

    HAS_TABULAR = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_TABULAR = False

from openbench.intelligence.skill import Skill  # noqa: E402 - after the sys.path shim

SDK_SKILLS_DIR = Path(__file__).resolve().parent.parent / "src" / "openbench" / "skills"

#: The whole point of the rework: a turn's source context must stay far
#: below what the old full-text path produced (550k+ chars here).
PROMPT_CHAR_CEILING = 40_000


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
@unittest.skipUnless(HAS_TABULAR, "duckdb, pandas and pyarrow are not installed")
class TestSourceContextEndToEnd(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved = {
            key: os.environ.get(key)
            for key in (
                "GENERAL_CHAT_SOURCE_INDEX_ENABLED",
                "GENERAL_CHAT_TABLE_PARQUET_ENABLED",
                "GENERAL_CHAT_SOURCE_CONTEXT_MODE",
                "GENERAL_CHAT_STORAGE_ROOT",
                "OPENBENCH_DOC_INDEX_URL",
                "GENERAL_CHAT_DATABASE_URL",
            )
        }
        os.environ["GENERAL_CHAT_SOURCE_INDEX_ENABLED"] = "1"
        os.environ["GENERAL_CHAT_TABLE_PARQUET_ENABLED"] = "1"
        os.environ["GENERAL_CHAT_SOURCE_CONTEXT_MODE"] = "auto"
        os.environ["GENERAL_CHAT_STORAGE_ROOT"] = str(self.root)
        os.environ.pop("OPENBENCH_DOC_INDEX_URL", None)
        os.environ.pop("GENERAL_CHAT_DATABASE_URL", None)

        source_index.reset_caches()
        self.index = source_index.get_document_index()
        self.index._embedding_provider = FakeEmbeddingProvider()
        self.index._dimension = 16
        self.catalog = source_index.get_table_catalog()

        self.records = [self._ingest_document(), self._ingest_csv()]
        set_source_scope(None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        set_source_scope(None)
        source_index.reset_caches()
        self._tmp.cleanup()

    def _ingest_document(self) -> SourceRecord:
        # Varied paragraphs, as a real report would be. Uniform filler
        # would make every chunk embed identically and turn ranking into
        # a coin flip, which tests the fixture rather than the pipeline.
        topics = [
            "distribusi armada logistik",
            "kapasitas gudang regional",
            "retensi pelanggan korporat",
            "biaya perawatan mesin",
            "pelatihan tenaga penjualan",
            "kepatuhan lingkungan pabrik",
            "rantai pasok bahan baku",
            "digitalisasi proses gudang",
        ]
        paragraphs = [
            f"Bagian {i} membahas {topics[i % len(topics)]} pada wilayah {i % 37}. "
            f"Catatan operasional nomor {i * 7} mencantumkan volume {i * 13} unit "
            f"dengan indeks efisiensi {i % 91} dan rasio pemanfaatan {i % 53} persen. "
            f"Tinjauan ini disusun oleh tim wilayah {i % 29} pada periode {1990 + (i % 30)}."
            for i in range(2100)
        ]
        paragraphs.insert(1000, "Marjin laba bersih tercatat sebesar dua belas koma empat persen.")
        text = "\n\n".join(paragraphs)
        self.assertGreater(len(text), 500_000)

        record = SourceRecord.create(
            session_id="s1",
            name="laporan-tahunan.pdf",
            kind="document",
            mime_type="application/pdf",
            size_bytes=len(text),
            text=text,
            owner="alice@example.com",
        )
        record.id = "source-doc"
        return source_index.index_source_record(record)

    def _ingest_csv(self) -> SourceRecord:
        path = self.root / "penjualan.csv"
        frame = pd.DataFrame(
            {
                "cabang": [f"Cabang{index % 5}" for index in range(50_000)],
                "nilai": list(range(50_000)),
            }
        )
        frame.to_csv(path, index=False)
        self.expected_total = int(frame["nilai"].sum())

        record = SourceRecord.create(
            session_id="s1",
            name="penjualan.csv",
            kind="spreadsheet",
            mime_type="text/csv",
            size_bytes=path.stat().st_size,
            text="### CSV: penjualan.csv (50000 rows)",
            owner="alice@example.com",
        )
        record.id = "source-csv"

        class _Stored:
            def __init__(self, file_path):
                self.path = str(file_path)

        return source_index.index_source_record(record, stored_file=_Stored(path))

    # --- the contract -----------------------------------------------------

    def test_both_sources_indexed(self):
        for record in self.records:
            with self.subTest(source=record.id):
                self.assertEqual(record.metadata["indexStatus"], "ready")

    def test_turn_context_stays_small(self):
        attachments = build_source_attachments(
            self.records, "berapa marjin laba bersih?", index=self.index
        )
        total = sum(len(a.extracted_text or "") for a in attachments)
        self.assertLess(
            total,
            PROMPT_CHAR_CEILING,
            f"source context was {total:,} chars; the old full-text path sent 550k+",
        )

    def test_no_truncation_markers_anywhere(self):
        attachments = build_source_attachments(
            self.records, "berapa marjin laba bersih?", index=self.index
        )
        joined = "\n".join(a.extracted_text or "" for a in attachments)
        self.assertNotIn("[TRUNCATED", joined)
        self.assertNotIn("[OMITTED", joined)

    def test_the_answer_is_retrieved_without_a_tool_call(self):
        attachments = build_source_attachments(
            self.records, "berapa marjin laba bersih tercatat?", index=self.index
        )
        joined = "\n".join(a.extracted_text or "" for a in attachments)
        self.assertIn("dua belas koma empat persen", joined)

    def test_scope_covers_both_sources(self):
        build_source_attachments(self.records, "berapa marjin laba bersih?", index=self.index)
        self.assertEqual(set(current_source_scope().source_ids), {"source-doc", "source-csv"})

    def test_retrieval_skill_reaches_the_document(self):
        build_source_attachments(self.records, "berapa marjin laba bersih?", index=self.index)
        skill = Skill.from_dir(SDK_SKILLS_DIR / "source-retrieval")
        tools = {name: fn for name, fn, _ in skill.tools}
        module = sys.modules["openbench_skill_source_retrieval"]
        module.bind(source_index=self.index, source_scope_provider=current_source_scope)
        try:
            result = tools["search_sources"]("marjin laba bersih")
            self.assertGreater(result["count"], 0)
            self.assertTrue(any("marjin" in hit["content"].lower() for hit in result["results"]))
        finally:
            module.bind(source_index=None, source_scope_provider=None)

    def test_sql_over_the_csv_is_arithmetically_correct(self):
        build_source_attachments(self.records, "berapa total nilai penjualan?", index=self.index)
        skill = Skill.from_dir(SDK_SKILLS_DIR / "table-query")
        tools = {name: fn for name, fn, _ in skill.tools}
        module = sys.modules["openbench_skill_table_query"]
        module.bind(table_catalog=self.catalog, source_scope_provider=current_source_scope)
        try:
            listed = tools["list_source_tables"]()
            self.assertEqual(listed["count"], 1)
            table = listed["tables"][0]["table"]

            result = tools["query_source_table"](f'SELECT SUM(nilai) AS total FROM "{table}"')
            self.assertNotIn("error", result)
            self.assertEqual(result["rows"][0][0], self.expected_total)

            grouped = tools["query_source_table"](
                f'SELECT cabang, SUM(nilai) AS total FROM "{table}" '
                "GROUP BY cabang ORDER BY total DESC"
            )
            self.assertEqual(grouped["row_count"], 5)
        finally:
            module.bind(table_catalog=None, source_scope_provider=None)

    def test_out_of_scope_source_is_unreachable_from_the_skills(self):
        set_source_scope(None)
        skill = Skill.from_dir(SDK_SKILLS_DIR / "source-retrieval")
        tools = {name: fn for name, fn, _ in skill.tools}
        module = sys.modules["openbench_skill_source_retrieval"]
        module.bind(source_index=self.index, source_scope_provider=current_source_scope)
        try:
            self.assertIn("error", tools["search_sources"]("marjin laba bersih"))
        finally:
            module.bind(source_index=None, source_scope_provider=None)


if __name__ == "__main__":
    unittest.main()
