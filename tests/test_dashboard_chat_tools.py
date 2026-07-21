"""Agent toolset tests for Dashboard Chat."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "examples" / "dashboard-chat" / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))


pytestmark = pytest.mark.integration

EXPECTED_TOOLS = {"get_database_schema", "validate_sql", "get_dashboard", "save_dashboard"}


def _make_sample_db(directory: Path) -> str:
    import sqlalchemy

    db_path = directory / "tools.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text("CREATE TABLE sales (id INTEGER PRIMARY KEY, amount REAL)")
        )
        connection.execute(sqlalchemy.text("INSERT INTO sales (amount) VALUES (10.0), (20.0)"))
    engine.dispose()
    return f"sqlite:///{db_path.as_posix()}"


class TestToolset(unittest.TestCase):
    def setUp(self):
        from dashboard_chat.connections import build_connection_store
        from dashboard_chat.dashboards import build_dashboard_store
        from dashboard_chat.tools import build_toolset

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.connections = build_connection_store(root)
        # Engines hold the sqlite file open — dispose before tmp cleanup
        # (LIFO: registered after the TemporaryDirectory, so runs first).
        self.addCleanup(lambda: self.connections.dispose_all())
        self.dashboards = build_dashboard_store(root)
        self.url = _make_sample_db(root)
        self.connections.set("alice", self.url)
        self.tools = build_toolset("alice", self.connections, self.dashboards)

    def _valid_spec(self) -> dict:
        return {
            "title": "Sales",
            "panels": [
                {
                    "id": "kpi-total",
                    "type": "kpi",
                    "title": "Total sales",
                    "width": "third",
                    "sql": "SELECT SUM(amount) AS value FROM sales",
                }
            ],
        }

    def test_registers_expected_tools(self):
        schemas = self.tools.get_schemas()
        names = {schema["function"]["name"] for schema in schemas}
        self.assertEqual(names, EXPECTED_TOOLS)

    def test_get_database_schema_text_only(self):
        result = self.tools.execute("get_database_schema")
        self.assertTrue(result["ok"])
        self.assertIn("sales:", result["schema"])
        # No row data — the table contents must not appear.
        self.assertNotIn("10.0", result["schema"])

    def test_validate_sql_ok_and_error(self):
        good = self.tools.execute("validate_sql", arguments={"sql": "SELECT amount FROM sales"})
        self.assertTrue(good["ok"])
        self.assertEqual(good["columns"], ["amount"])
        bad = self.tools.execute("validate_sql", arguments={"sql": "SELECT nope FROM sales"})
        self.assertFalse(bad["ok"])
        self.assertIn("nope", bad["error"])

    def test_save_and_get_dashboard(self):
        result = self.tools.execute(
            "save_dashboard", arguments={"spec": json.dumps(self._valid_spec())}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], 1)
        loaded = self.tools.execute("get_dashboard")
        self.assertEqual(loaded["dashboard"]["title"], "Sales")

    def test_save_rejects_non_select_panel(self):
        spec = self._valid_spec()
        spec["panels"][0]["sql"] = "DELETE FROM sales"
        result = self.tools.execute("save_dashboard", arguments={"spec": json.dumps(spec)})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["panelId"], "kpi-total")
        # Nothing was persisted.
        self.assertIsNone(self.dashboards.get("alice"))

    def test_save_rejects_invalid_json(self):
        result = self.tools.execute("save_dashboard", arguments={"spec": "not json"})
        self.assertFalse(result["ok"])

    def test_owner_scoping(self):
        from dashboard_chat.tools import build_toolset

        bob_tools = build_toolset("bob", self.connections, self.dashboards)
        result = bob_tools.execute("get_database_schema")
        self.assertFalse(result["ok"])  # bob has no connection

    def test_no_connection_paths(self):
        from dashboard_chat.tools import build_toolset

        tools = build_toolset("carol", self.connections, self.dashboards)
        for call in (
            ("validate_sql", {"sql": "SELECT 1"}),
            ("save_dashboard", {"spec": json.dumps(self._valid_spec())}),
        ):
            result = tools.execute(call[0], arguments=call[1])
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
