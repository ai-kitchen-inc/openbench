"""Tests for the DuckDB SQL guard and query engine.

The agent writes this SQL, so these tests are the security boundary:
they assert that file and network access stay closed even when the
query text asks for them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.data.tabular.query import (
    DuckDBQueryEngine,
    SQLGuardError,
    strip_sql_comments,
    validate_sql,
)

try:
    import duckdb  # noqa: F401
    import pandas as pd
    import pyarrow  # noqa: F401

    HAS_TABULAR = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_TABULAR = False


class TestStripComments(unittest.TestCase):
    def test_removes_line_comments(self):
        self.assertNotIn("DROP", strip_sql_comments("SELECT 1 -- DROP TABLE t").upper())

    def test_removes_block_comments(self):
        self.assertNotIn("DROP", strip_sql_comments("SELECT /* DROP TABLE t */ 1").upper())

    def test_removes_multiline_block_comments(self):
        cleaned = strip_sql_comments("SELECT 1\n/* line one\nDROP TABLE t\n*/\n")
        self.assertNotIn("DROP", cleaned.upper())


class TestValidateSQL(unittest.TestCase):
    def test_allows_read_only_statements(self):
        for sql in (
            "SELECT * FROM sales",
            "select region, sum(amount) from sales group by 1",
            "WITH t AS (SELECT 1 AS x) SELECT * FROM t",
            "DESCRIBE sales",
            "SUMMARIZE sales",
            "EXPLAIN SELECT * FROM sales",
            "  SELECT 1  ",
            "SELECT 1;",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(validate_sql(sql))

    def test_strips_trailing_semicolon(self):
        self.assertEqual(validate_sql("SELECT 1;"), "SELECT 1")

    def test_rejects_empty(self):
        for sql in ("", "   ", ";", "-- just a comment"):
            with self.subTest(sql=sql), self.assertRaises(SQLGuardError):
                validate_sql(sql)

    def test_rejects_write_statements(self):
        for sql in (
            "INSERT INTO sales VALUES (1)",
            "UPDATE sales SET amount = 0",
            "DELETE FROM sales",
            "DROP TABLE sales",
            "CREATE TABLE evil AS SELECT 1",
            "ALTER TABLE sales ADD COLUMN x INT",
            "TRUNCATE sales",
        ):
            with self.subTest(sql=sql), self.assertRaises(SQLGuardError):
                validate_sql(sql)

    def test_rejects_filesystem_and_network_access(self):
        for sql in (
            "COPY sales TO '/tmp/out.csv'",
            "ATTACH '/etc/passwd' AS leak",
            "INSTALL httpfs",
            "LOAD httpfs",
            "PRAGMA database_list",
            "SELECT * FROM read_parquet('/etc/passwd')",
            "SELECT * FROM read_csv_auto('/etc/passwd')",
            "SELECT * FROM read_json('/etc/passwd')",
            "SELECT * FROM parquet_scan('/etc/passwd')",
            "SELECT * FROM glob('/**')",
            "SELECT * FROM sqlite_scan('db.sqlite', 't')",
            "SELECT * FROM postgres_scan('host=x', 'public', 't')",
            "SELECT getenv('OPENAI_API_KEY')",
            "SET enable_external_access=true",
        ):
            with self.subTest(sql=sql), self.assertRaises(SQLGuardError):
                validate_sql(sql)

    def test_rejects_chained_statements(self):
        for sql in (
            "SELECT 1; DROP TABLE sales",
            "SELECT 1;SELECT 2",
        ):
            with self.subTest(sql=sql), self.assertRaises(SQLGuardError):
                validate_sql(sql)

    def test_rejects_comment_obfuscated_statements(self):
        for sql in (
            "SELECT 1 --\n; DROP TABLE sales",
            "/* hide */ DROP TABLE sales",
            "SELECT * FROM /* x */ read_parquet('/etc/passwd')",
            "--\nATTACH '/etc/passwd' AS leak",
        ):
            with self.subTest(sql=sql), self.assertRaises(SQLGuardError):
                validate_sql(sql)

    def test_rejects_cte_leading_into_a_write(self):
        # `WITH` is an allowed leading keyword, so the deny list is what
        # stops a CTE that ends in a mutation.
        with self.assertRaises(SQLGuardError):
            validate_sql("WITH t AS (SELECT 1) INSERT INTO sales SELECT * FROM t")


@unittest.skipUnless(HAS_TABULAR, "duckdb, pandas and pyarrow are not installed")
class DuckDBEngineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        frame = pd.DataFrame(
            {
                "region": ["North", "South", "North", "East"],
                "amount": [100, 250, 50, 75],
            }
        )
        self.parquet = self.root / "sales.parquet"
        frame.to_parquet(self.parquet)
        self.tables = {"sales": str(self.parquet)}
        self.engine = DuckDBQueryEngine(max_rows=100, timeout_seconds=15.0)

    def tearDown(self):
        self._tmp.cleanup()


class TestQueryExecution(DuckDBEngineTestCase):
    def test_select_returns_rows(self):
        result = self.engine.run("SELECT * FROM sales ORDER BY amount", tables=self.tables)
        self.assertEqual(result.columns, ["region", "amount"])
        self.assertEqual(result.row_count, 4)
        self.assertFalse(result.truncated)

    def test_aggregation_is_arithmetically_correct(self):
        result = self.engine.run(
            "SELECT region, SUM(amount) AS total FROM sales GROUP BY region ORDER BY total DESC",
            tables=self.tables,
        )
        totals = {row[0]: row[1] for row in result.rows}
        self.assertEqual(totals["North"], 150)
        self.assertEqual(totals["South"], 250)
        self.assertEqual(totals["East"], 75)

    def test_cte_query_works(self):
        result = self.engine.run(
            "WITH big AS (SELECT * FROM sales WHERE amount > 60) SELECT COUNT(*) FROM big",
            tables=self.tables,
        )
        self.assertEqual(result.rows[0][0], 3)

    def test_describe_works(self):
        result = self.engine.run("DESCRIBE sales", tables=self.tables)
        self.assertGreater(result.row_count, 0)

    def test_row_cap_marks_truncated(self):
        engine = DuckDBQueryEngine(max_rows=2)
        result = engine.run("SELECT * FROM sales", tables=self.tables)
        self.assertEqual(result.row_count, 2)
        self.assertTrue(result.truncated)

    def test_max_rows_argument_is_clamped_to_engine_limit(self):
        engine = DuckDBQueryEngine(max_rows=2)
        result = engine.run("SELECT * FROM sales", tables=self.tables, max_rows=1000)
        self.assertEqual(result.row_count, 2)

    def test_elapsed_and_sql_are_reported(self):
        result = self.engine.run("SELECT 1 AS x", tables=self.tables)
        self.assertGreaterEqual(result.elapsed_ms, 0)
        self.assertEqual(result.sql, "SELECT 1 AS x")

    def test_missing_parquet_file_warns_instead_of_raising(self):
        result = self.engine.run(
            "SELECT 1 AS x", tables={"ghost": str(self.root / "absent.parquet")}
        )
        self.assertTrue(any("missing its data file" in w for w in result.warnings))

    def test_bad_column_raises_runtime_error_with_duckdb_message(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.engine.run("SELECT no_such_column FROM sales", tables=self.tables)
        self.assertIn("no_such_column", str(ctx.exception))

    def test_result_dict_shape(self):
        payload = self.engine.run("SELECT 1 AS x", tables=self.tables).to_dict()
        for key in ("columns", "rows", "row_count", "truncated", "elapsed_ms", "sql"):
            self.assertIn(key, payload)


class TestEngineLockdown(DuckDBEngineTestCase):
    """The guard is layer one; these assert layer two actually engages."""

    def test_external_access_is_disabled_after_prepare(self):
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            self.engine._prepare(conn, self.tables)
            value = conn.execute("SELECT current_setting('enable_external_access')").fetchone()[0]
            self.assertIn(str(value).lower(), ("false", "0"))
        finally:
            conn.close()

    def test_configuration_is_locked_after_prepare(self):
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            self.engine._prepare(conn, self.tables)
            with self.assertRaises(duckdb.Error):
                conn.execute("SET enable_external_access=true")
        finally:
            conn.close()

    def test_file_read_fails_on_a_prepared_connection(self):
        # Belt and braces: even if the text guard were bypassed, the
        # locked connection must refuse to touch the filesystem.
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            self.engine._prepare(conn, self.tables)
            with self.assertRaises(duckdb.Error):
                conn.execute(f"SELECT * FROM read_parquet('{self.parquet.as_posix()}')")
        finally:
            conn.close()

    def test_invalid_table_alias_is_rejected(self):
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            with self.assertRaises(SQLGuardError):
                self.engine._prepare(conn, {"bad; DROP TABLE t": str(self.parquet)})
        finally:
            conn.close()

    def test_guard_rejects_before_execution(self):
        with self.assertRaises(SQLGuardError):
            self.engine.run("DROP TABLE sales", tables=self.tables)


class TestPayloadCap(DuckDBEngineTestCase):
    def test_large_result_is_capped(self):
        engine = DuckDBQueryEngine(max_rows=100_000, max_payload_chars=500)
        result = engine.run(
            "SELECT range AS n, repeat('x', 100) AS pad FROM range(5000)", tables=self.tables
        )
        self.assertTrue(result.truncated)
        self.assertLess(result.row_count, 5000)


if __name__ == "__main__":
    unittest.main()
