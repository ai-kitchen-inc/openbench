"""Tests for Parquet conversion and the table catalog."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.data.tabular.catalog import SQLiteTableCatalog
from openbench.data.tabular.converter import (
    TableArtifact,
    TableColumn,
    convert_to_parquet,
    is_tabular_file,
)

try:
    import pandas as pd
    import pyarrow  # noqa: F401

    HAS_TABULAR = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_TABULAR = False


class TestIsTabularFile(unittest.TestCase):
    def test_recognizes_extensions(self):
        for name in ("data.csv", "data.TSV", "book.xlsx", "legacy.xls", "macro.xlsm"):
            self.assertTrue(is_tabular_file(name), name)

    def test_rejects_other_files(self):
        for name in ("report.pdf", "notes.md", "photo.png", "audio.mp3"):
            self.assertFalse(is_tabular_file(name), name)

    def test_recognizes_mime_when_extension_missing(self):
        self.assertTrue(is_tabular_file("upload", "text/csv"))
        self.assertTrue(
            is_tabular_file(
                "upload",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )
        self.assertFalse(is_tabular_file("upload", "application/pdf"))


@unittest.skipUnless(HAS_TABULAR, "pandas and pyarrow are not installed")
class ConversionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dest = self.root / "tables"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_csv(self, name: str, text: str, encoding: str = "utf-8") -> Path:
        path = self.root / name
        path.write_text(text, encoding=encoding)
        return path


class TestCsvConversion(ConversionTestCase):
    def test_csv_produces_one_artifact(self):
        path = self._write_csv("sales.csv", "region,amount\nNorth,100\nSouth,250\nNorth,50\n")
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-1")
        self.assertEqual(len(artifacts), 1)
        artifact = artifacts[0]
        self.assertEqual(artifact.row_count, 3)
        self.assertEqual([column.name for column in artifact.columns], ["region", "amount"])
        self.assertTrue(Path(artifact.parquet_path).exists())
        self.assertEqual(artifact.table_id, f"source-1--{artifact.name}")

    def test_tsv_uses_tab_separator(self):
        path = self._write_csv("data.tsv", "a\tb\n1\t2\n")
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-tsv")
        self.assertEqual([column.name for column in artifacts[0].columns], ["a", "b"])

    def test_bom_encoded_csv(self):
        path = self._write_csv("bom.csv", "name,value\nAda,1\n", encoding="utf-8-sig")
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-bom")
        self.assertEqual([column.name for column in artifacts[0].columns], ["name", "value"])

    def test_latin1_csv_falls_back(self):
        path = self.root / "latin.csv"
        path.write_bytes("name,city\nJos\xe9,Bogot\xe1\n".encode("latin-1"))
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-latin")
        self.assertEqual(artifacts[0].row_count, 1)

    def test_empty_csv_yields_no_artifacts(self):
        path = self._write_csv("empty.csv", "a,b\n")
        self.assertEqual(convert_to_parquet(path, dest_dir=self.dest, source_id="s"), [])

    def test_duplicate_headers_yield_unique_column_names(self):
        # pandas already disambiguates duplicate CSV headers on read;
        # what matters here is that Parquet never sees a repeated name.
        path = self._write_csv("dupes.csv", "amount,amount\n1,2\n")
        artifact = convert_to_parquet(path, dest_dir=self.dest, source_id="source-dupe")[0]
        names = [column.name for column in artifact.columns]
        self.assertEqual(len(names), len(set(names)))

    def test_max_rows_truncates_and_warns(self):
        rows = "\n".join(f"{i},{i * 2}" for i in range(50))
        path = self._write_csv("big.csv", f"a,b\n{rows}\n")
        artifact = convert_to_parquet(
            path, dest_dir=self.dest, source_id="source-cap", max_rows=10
        )[0]
        self.assertEqual(artifact.row_count, 10)
        self.assertTrue(any("truncated" in warning for warning in artifact.warnings))

    def test_unreadable_file_raises_value_error(self):
        path = self.root / "missing.csv"
        with self.assertRaises(ValueError):
            convert_to_parquet(path, dest_dir=self.dest, source_id="source-x")

    def test_parquet_is_zstd_compressed_by_default(self):
        import pyarrow.parquet as pq

        path = self._write_csv("compressed.csv", "a,b\n1,2\n3,4\n")
        artifact = convert_to_parquet(path, dest_dir=self.dest, source_id="source-zstd")[0]
        metadata = pq.ParquetFile(artifact.parquet_path).metadata
        codecs = {
            metadata.row_group(rg).column(col).compression
            for rg in range(metadata.num_row_groups)
            for col in range(metadata.num_columns)
        }
        self.assertEqual(codecs, {"ZSTD"})


@unittest.skipUnless(HAS_TABULAR, "pandas and pyarrow are not installed")
class TestDedupeColumns(unittest.TestCase):
    """Direct cover for the rename guard.

    Both pandas readers disambiguate duplicate headers themselves, so
    this is the only way to exercise the fallback that keeps Parquet
    from ever seeing a repeated field name.
    """

    def test_repeated_names_are_renamed_and_warned(self):
        from openbench.data.tabular.converter import _dedupe_columns

        frame = pd.DataFrame([[1, 2, 3]], columns=["amount", "amount", "amount"])
        frame, warnings = _dedupe_columns(frame)
        self.assertEqual(list(frame.columns), ["amount", "amount_1", "amount_2"])
        self.assertEqual(len(warnings), 2)
        self.assertIn("duplicate column", warnings[0])

    def test_blank_names_become_column(self):
        from openbench.data.tabular.converter import _dedupe_columns

        frame, _ = _dedupe_columns(pd.DataFrame([[1]], columns=["   "]))
        self.assertEqual(list(frame.columns), ["column"])

    def test_unique_names_are_untouched(self):
        from openbench.data.tabular.converter import _dedupe_columns

        frame, warnings = _dedupe_columns(pd.DataFrame([[1, 2]], columns=["a", "b"]))
        self.assertEqual(list(frame.columns), ["a", "b"])
        self.assertEqual(warnings, [])


@unittest.skipUnless(HAS_TABULAR, "pandas and pyarrow are not installed")
class TestExcelConversion(ConversionTestCase):
    def _write_workbook(self, name: str, sheets: dict) -> Path:
        path = self.root / name
        with pd.ExcelWriter(path) as writer:
            for sheet_name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=sheet_name, index=False)
        return path

    def test_multi_sheet_workbook_yields_one_artifact_per_sheet(self):
        path = self._write_workbook(
            "book.xlsx",
            {
                "Ringkasan": pd.DataFrame({"cabang": ["A", "B"], "nilai": [10, 20]}),
                "Detail": pd.DataFrame({"id": [1, 2, 3], "qty": [4, 5, 6]}),
            },
        )
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-xl")
        self.assertEqual(len(artifacts), 2)
        display = sorted(artifact.display_name for artifact in artifacts)
        self.assertEqual(display, ["Detail", "Ringkasan"])
        for artifact in artifacts:
            self.assertTrue(Path(artifact.parquet_path).exists())

    def test_empty_sheet_is_skipped(self):
        path = self._write_workbook(
            "mixed.xlsx",
            {
                "Data": pd.DataFrame({"x": [1, 2]}),
                "Blank": pd.DataFrame(),
            },
        )
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-mixed")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].display_name, "Data")

    def test_sheet_names_become_sql_safe_aliases(self):
        path = self._write_workbook("odd.xlsx", {"2024 Sales (Q1)": pd.DataFrame({"v": [1]})})
        artifact = convert_to_parquet(path, dest_dir=self.dest, source_id="source-odd")[0]
        self.assertRegex(artifact.name, r"^[A-Za-z_][A-Za-z0-9_]*$")


@unittest.skipUnless(HAS_TABULAR, "pandas and pyarrow are not installed")
class TestMixedTypeColumns(ConversionTestCase):
    """Sheets that mix text and numbers in one column must still convert.

    This is the normal shape of a real spreadsheet: a merged title row
    above the data, or "N/A" in a numeric column. Arrow infers one type
    per column and raises ``Expected bytes, got a 'int' object``, which
    silently dropped 35 of 45 real spreadsheets in production before
    this was handled.
    """

    def _mixed_workbook(self) -> Path:
        path = self.root / "rab.xlsx"
        frame = pd.DataFrame(
            {
                # Title text sitting above numeric data, as Excel exports it.
                "RENCANA ANGGARAN BIAYA (RAB)": ["JUDUL", 1, 2, 3],
                "harga": [1000, 2000, 3000, 4000],
                "catatan": ["a", "b", "c", "d"],
            }
        )
        frame.to_excel(path, index=False)
        return path

    def test_mixed_column_sheet_still_produces_a_table(self):
        artifacts = convert_to_parquet(
            self._mixed_workbook(), dest_dir=self.dest, source_id="source-mixed"
        )
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].row_count, 4)
        self.assertTrue(Path(artifacts[0].parquet_path).exists())

    def test_offending_column_is_reported_as_coerced(self):
        artifact = convert_to_parquet(
            self._mixed_workbook(), dest_dir=self.dest, source_id="source-mixed"
        )[0]
        self.assertTrue(
            any("stored as text" in warning for warning in artifact.warnings),
            artifact.warnings,
        )

    def test_clean_numeric_columns_keep_their_type(self):
        artifact = convert_to_parquet(
            self._mixed_workbook(), dest_dir=self.dest, source_id="source-mixed"
        )[0]
        harga = next(column for column in artifact.columns if column.name == "harga")
        # Only the offending column is downgraded; SQL aggregation on the
        # clean numeric columns must keep working.
        self.assertIn("int", harga.dtype)
        self.assertIsNotNone(harga.min)

    def test_parquet_is_queryable_after_coercion(self):
        try:
            import duckdb
        except ImportError:
            self.skipTest("duckdb is not installed")
        artifact = convert_to_parquet(
            self._mixed_workbook(), dest_dir=self.dest, source_id="source-mixed"
        )[0]
        conn = duckdb.connect(":memory:")
        try:
            total = conn.execute(
                f"SELECT SUM(harga) FROM read_parquet('{Path(artifact.parquet_path).as_posix()}')"
            ).fetchone()[0]
            self.assertEqual(total, 10000)
        finally:
            conn.close()

    def test_all_null_object_column_converts(self):
        path = self.root / "nulls.xlsx"
        pd.DataFrame({"a": [1, 2], "b": [None, None]}).to_excel(path, index=False)
        artifacts = convert_to_parquet(path, dest_dir=self.dest, source_id="source-null")
        self.assertEqual(len(artifacts), 1)


@unittest.skipUnless(HAS_TABULAR, "pandas and pyarrow are not installed")
class TestSchemaCard(ConversionTestCase):
    def setUp(self):
        super().setUp()
        path = self.root / "profile.csv"
        rows = "\n".join(f"2024-01-0{(i % 9) + 1},Region{i % 3},{i * 100}" for i in range(30))
        path.write_text(f"tanggal,cabang,nilai\n{rows}\n", encoding="utf-8")
        self.artifact = convert_to_parquet(path, dest_dir=self.dest, source_id="source-card")[0]

    def test_card_names_every_column(self):
        card = self.artifact.schema_card()
        for column in self.artifact.columns:
            self.assertIn(column.name, card)

    def test_card_reports_row_count(self):
        self.assertIn("30", self.artifact.schema_card())

    def test_card_stays_compact(self):
        self.assertLess(len(self.artifact.schema_card()), 2000)

    def test_numeric_column_carries_min_and_max(self):
        nilai = next(c for c in self.artifact.columns if c.name == "nilai")
        self.assertIsNotNone(nilai.min)
        self.assertIsNotNone(nilai.max)

    def test_text_column_carries_distinct_estimate(self):
        cabang = next(c for c in self.artifact.columns if c.name == "cabang")
        self.assertEqual(cabang.distinct_estimate, 3)

    def test_card_truncates_column_list(self):
        card = self.artifact.schema_card(max_columns=1)
        self.assertIn("more columns", card)

    def test_round_trip_through_dict(self):
        restored = TableArtifact.from_dict(self.artifact.to_dict())
        self.assertEqual(restored.table_id, self.artifact.table_id)
        self.assertEqual(restored.row_count, self.artifact.row_count)
        self.assertEqual(
            [column.name for column in restored.columns],
            [column.name for column in self.artifact.columns],
        )
        self.assertIsInstance(restored.columns[0], TableColumn)


class TestSQLiteTableCatalog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.catalog = SQLiteTableCatalog(self.root / "tables.sqlite3")

    def tearDown(self):
        self.catalog.close()
        self._tmp.cleanup()

    def _artifact(self, source_id: str, name: str) -> TableArtifact:
        return TableArtifact(
            table_id=f"{source_id}--{name}",
            source_id=source_id,
            name=name,
            display_name=name.title(),
            parquet_path=str(self.root / f"{name}.parquet"),
            row_count=10,
            columns=[TableColumn(name="a", dtype="int64")],
            sample_rows=[{"a": 1}],
            source_hash="sha256:abc",
            created_at="2026-07-31T00:00:00+00:00",
        )

    def test_upsert_and_get(self):
        artifact = self._artifact("source-1", "sales")
        self.catalog.upsert(artifact, session_id="s1", owner="alice@example.com")
        fetched = self.catalog.get(artifact.table_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "sales")
        self.assertEqual(fetched.columns[0].name, "a")

    def test_upsert_is_idempotent(self):
        artifact = self._artifact("source-1", "sales")
        self.catalog.upsert(artifact, session_id="s1")
        self.catalog.upsert(artifact, session_id="s1")
        self.assertEqual(len(self.catalog.list_for(source_ids=["source-1"])), 1)

    def test_get_by_name(self):
        self.catalog.upsert(self._artifact("source-1", "sales"), session_id="s1")
        self.assertIsNotNone(self.catalog.get_by_name("sales"))

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.catalog.get("nope"))
        self.assertIsNone(self.catalog.get_by_name("nope"))

    def test_scope_filters(self):
        self.catalog.upsert(
            self._artifact("source-1", "sales"), session_id="s1", owner="alice@example.com"
        )
        self.catalog.upsert(
            self._artifact("source-2", "costs"), session_id="s2", owner="bob@example.com"
        )
        self.assertEqual(len(self.catalog.list_for(source_ids=["source-1"])), 1)
        self.assertEqual(len(self.catalog.list_for(session_id="s2")), 1)
        self.assertEqual(len(self.catalog.list_for(owner="alice@example.com")), 1)
        self.assertEqual(len(self.catalog.list_for()), 2)

    def test_empty_source_ids_matches_nothing(self):
        self.catalog.upsert(self._artifact("source-1", "sales"), session_id="s1")
        self.assertEqual(self.catalog.list_for(source_ids=[]), [])

    def test_delete_source_removes_all_its_tables(self):
        self.catalog.upsert(self._artifact("source-1", "sheet_a"), session_id="s1")
        self.catalog.upsert(self._artifact("source-1", "sheet_b"), session_id="s1")
        self.assertEqual(self.catalog.delete_source("source-1"), 2)
        self.assertEqual(self.catalog.list_for(source_ids=["source-1"]), [])

    def test_delete_unknown_source_is_noop(self):
        self.assertEqual(self.catalog.delete_source("source-missing"), 0)

    def test_rejects_unsafe_table_name(self):
        with self.assertRaises(ValueError):
            SQLiteTableCatalog(self.root / "x.sqlite3", table_name="t; DROP TABLE users")


if __name__ == "__main__":
    unittest.main()
