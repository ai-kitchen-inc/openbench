"""Connection store and schema introspection tests for Dashboard Chat."""

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


def _make_sample_db(directory: Path) -> str:
    import sqlalchemy

    db_path = directory / "sample.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
        )
        connection.execute(
            sqlalchemy.text(
                "CREATE TABLE orders (id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL REFERENCES users(id), total REAL)"
            )
        )
    engine.dispose()
    return f"sqlite:///{db_path.as_posix()}"


class TestConnectionStore(unittest.TestCase):
    def setUp(self):
        from dashboard_chat.connections import build_connection_store

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = build_connection_store(self.root)
        # Engines hold the sqlite file open — dispose before tmp cleanup
        # (LIFO: registered after the TemporaryDirectory, so runs first).
        self.addCleanup(lambda: self.store.dispose_all())
        self.url = _make_sample_db(self.root)

    def test_get_before_set(self):
        self.assertIsNone(self.store.get("alice"))
        self.assertIsNone(self.store.engine_for("alice"))

    def test_set_get_remove(self):
        record = self.store.set("alice", self.url)
        self.assertEqual(record.dialect, "sqlite")
        loaded = self.store.get("alice")
        self.assertEqual(loaded.url, self.url)
        self.store.remove("alice")
        self.assertIsNone(self.store.get("alice"))

    def test_per_user_isolation(self):
        self.store.set("alice", self.url)
        self.assertIsNone(self.store.get("bob"))

    def test_engine_cached_and_evicted(self):
        self.store.set("alice", self.url)
        engine_a = self.store.engine_for("alice")
        self.assertIs(engine_a, self.store.engine_for("alice"))
        self.store.set("alice", self.url)
        # Same URL re-set still evicts — a fresh engine is built on demand.
        engine_b = self.store.engine_for("alice")
        self.assertIsNotNone(engine_b)

    def test_connection_test(self):
        from dashboard_chat.connections import test_connection
        from sqlalchemy.exc import OperationalError

        test_connection(self.url)
        with self.assertRaises(OperationalError):
            test_connection("sqlite:///Z:/does/not/exist/dir/x.db")

    def test_redact_url(self):
        from dashboard_chat.connections import redact_url

        redacted = redact_url("postgresql://user:hunter2@localhost:5432/db")
        self.assertNotIn("hunter2", redacted)
        self.assertIn("***", redacted)
        # No password → unchanged.
        self.assertEqual(redact_url(self.url), self.url)


class TestNormalizeDriver(unittest.TestCase):
    def _find_spec(self, installed: set[str]):
        return lambda name: object() if name in installed else None

    def test_bare_postgres_rewritten_to_psycopg3(self):
        from unittest.mock import patch

        from dashboard_chat.connections import normalize_driver

        with patch("importlib.util.find_spec", self._find_spec({"psycopg"})):
            result = normalize_driver("postgresql://user:hunter2@localhost:5432/db")
        self.assertEqual(result, "postgresql+psycopg://user:hunter2@localhost:5432/db")

    def test_bare_postgres_kept_when_psycopg2_installed(self):
        from unittest.mock import patch

        from dashboard_chat.connections import normalize_driver

        url = "postgresql://user:pw@localhost/db"
        with patch("importlib.util.find_spec", self._find_spec({"psycopg2", "psycopg"})):
            self.assertEqual(normalize_driver(url), url)

    def test_explicit_driver_untouched(self):
        from unittest.mock import patch

        from dashboard_chat.connections import normalize_driver

        url = "postgresql+psycopg2://user:pw@localhost/db"
        with patch("importlib.util.find_spec", self._find_spec({"psycopg"})):
            self.assertEqual(normalize_driver(url), url)

    def test_bare_mysql_rewritten_to_pymysql(self):
        from unittest.mock import patch

        from dashboard_chat.connections import normalize_driver

        with patch("importlib.util.find_spec", self._find_spec({"pymysql"})):
            result = normalize_driver("mysql://user:pw@localhost:3306/db")
        self.assertEqual(result, "mysql+pymysql://user:pw@localhost:3306/db")

    def test_sqlite_untouched(self):
        from dashboard_chat.connections import normalize_driver

        self.assertEqual(normalize_driver("sqlite:///x.db"), "sqlite:///x.db")


class TestIntrospection(unittest.TestCase):
    def setUp(self):
        import sqlalchemy

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        url = _make_sample_db(Path(self._tmp.name))
        self.engine = sqlalchemy.create_engine(url)
        self.addCleanup(self.engine.dispose)

    def test_schema_structure(self):
        from dashboard_chat.connections import introspect_schema

        schema = introspect_schema(self.engine)
        self.assertEqual(schema["dialect"], "sqlite")
        names = [table["name"] for table in schema["tables"]]
        self.assertEqual(names, ["orders", "users"])
        orders = schema["tables"][0]
        id_column = next(column for column in orders["columns"] if column["name"] == "id")
        self.assertTrue(id_column["pk"])
        self.assertEqual(orders["foreignKeys"][0]["refTable"], "users")

    def test_schema_as_text(self):
        from dashboard_chat.connections import introspect_schema, schema_as_text

        text = schema_as_text(introspect_schema(self.engine))
        self.assertIn("dialect: sqlite", text)
        self.assertIn("orders:", text)
        self.assertIn("FK->users.id", text)
        self.assertIn("id INTEGER PK", text)
        # Structure only — never row data.
        self.assertNotIn("SELECT", text.upper())


if __name__ == "__main__":
    unittest.main()
