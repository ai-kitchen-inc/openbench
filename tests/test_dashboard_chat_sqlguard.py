"""SQL guard tests for Dashboard Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pytest

DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "examples" / "dashboard-chat" / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))


pytestmark = pytest.mark.integration


class TestIsSelectOnly(unittest.TestCase):
    def test_plain_select_allowed(self):
        from dashboard_chat.sqlguard import is_select_only

        self.assertTrue(is_select_only("SELECT * FROM t"))
        self.assertTrue(is_select_only("  select a, b from t where x = 1  "))

    def test_cte_allowed(self):
        from dashboard_chat.sqlguard import is_select_only

        self.assertTrue(is_select_only("WITH x AS (SELECT 1 AS v) SELECT v FROM x"))

    def test_dml_ddl_rejected(self):
        from dashboard_chat.sqlguard import is_select_only

        for statement in (
            "DROP TABLE t",
            "DELETE FROM t",
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET a = 1",
            "CREATE TABLE x (a int)",
            "PRAGMA table_info(t)",
            "ATTACH DATABASE 'x' AS y",
            "SELECT * INTO backup FROM t",
            "",
        ):
            self.assertFalse(is_select_only(statement), statement)

    def test_comment_smuggling_rejected(self):
        from dashboard_chat.sqlguard import is_select_only

        self.assertFalse(is_select_only("SELECT 1; -- ok\nDROP TABLE t"))
        self.assertFalse(is_select_only("/* x */ DELETE FROM t"))

    def test_multi_statement_rejected(self):
        from dashboard_chat.sqlguard import is_select_only

        self.assertFalse(is_select_only("SELECT 1; SELECT 2"))
        self.assertTrue(is_select_only("SELECT 1;"))


class TestApplyLimit(unittest.TestCase):
    def test_appends_missing_limit(self):
        from dashboard_chat.sqlguard import apply_limit

        self.assertEqual(apply_limit("SELECT 1", 10), "SELECT 1 LIMIT 10")
        self.assertEqual(apply_limit("SELECT 1;", 10), "SELECT 1 LIMIT 10")

    def test_replaces_larger_limit(self):
        from dashboard_chat.sqlguard import apply_limit

        self.assertEqual(apply_limit("SELECT 1 LIMIT 99999", 10), "SELECT 1 LIMIT 10")

    def test_keeps_smaller_limit(self):
        from dashboard_chat.sqlguard import apply_limit

        self.assertEqual(apply_limit("SELECT 1 LIMIT 5", 10), "SELECT 1 LIMIT 5")


class TestExecuteSelect(unittest.TestCase):
    def setUp(self):
        import sqlalchemy

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db_path = Path(self._tmp.name) / "test.db"
        self.engine = sqlalchemy.create_engine(f"sqlite:///{db_path.as_posix()}")
        with self.engine.begin() as connection:
            connection.execute(
                sqlalchemy.text(
                    "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL)"
                )
            )
            for index in range(20):
                connection.execute(
                    sqlalchemy.text("INSERT INTO items (name, price) VALUES (:n, :p)"),
                    {"n": f"item-{index}", "p": float(index)},
                )
        self.addCleanup(self.engine.dispose)

    def test_rows_and_columns(self):
        from dashboard_chat.sqlguard import execute_select

        result = execute_select(self.engine, "SELECT name, price FROM items ORDER BY id")
        self.assertEqual(result.columns, ["name", "price"])
        self.assertEqual(len(result.rows), 20)
        self.assertEqual(result.rows[0], ["item-0", 0.0])
        self.assertFalse(result.truncated)

    def test_row_cap(self):
        from dashboard_chat.sqlguard import execute_select

        result = execute_select(self.engine, "SELECT * FROM items", limit=5)
        self.assertEqual(len(result.rows), 5)
        self.assertTrue(result.truncated)

    def test_non_select_raises(self):
        from dashboard_chat.sqlguard import execute_select

        with self.assertRaises(ValueError):
            execute_select(self.engine, "DELETE FROM items")

    def test_validate_returns_columns_never_rows(self):
        from dashboard_chat.sqlguard import validate_select

        verdict = validate_select(self.engine, "SELECT name, price FROM items")
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["columns"], ["name", "price"])
        self.assertNotIn("rows", verdict)

    def test_validate_reports_driver_error(self):
        from dashboard_chat.sqlguard import validate_select

        verdict = validate_select(self.engine, "SELECT missing_column FROM items")
        self.assertFalse(verdict["ok"])
        self.assertIn("missing_column", verdict["error"])

    def test_validate_rejects_non_select(self):
        from dashboard_chat.sqlguard import validate_select

        verdict = validate_select(self.engine, "UPDATE items SET price = 0")
        self.assertFalse(verdict["ok"])


if __name__ == "__main__":
    unittest.main()
