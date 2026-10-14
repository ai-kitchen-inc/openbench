"""Tests for the live-dashboard project skill, registry helpers and MCP seeding."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.live_dashboard import (  # noqa: E402
    JsonLiveDashboardStore,
    LiveDashboardHub,
    QueryOutcome,
)
from general_chat.mcp_bootstrap import (  # noqa: E402
    DEFAULT_DB_SERVER_CONFIG,
    bundled_mcp_config_names,
    seed_all_mcp_registry,
)
from general_chat.mcp_registry import MCPRegistryError, MCPServerRegistryStore  # noqa: E402

from openbench.chat import render_queue  # noqa: E402
from openbench.intelligence.skill_registry import SkillRegistry  # noqa: E402

SKILL_DIR = (
    Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "skills" / "live-dashboard"
)
CONFIG_DIR = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "mcp"

QUERIES = {
    "by_region": "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region",
    "total": "SELECT SUM(revenue) AS total FROM sales",
}
VIEW_MODEL = {
    "kpis": [{"label": "Total", "dataset": "total", "value_column": "total"}],
    "sections": [
        {
            "title": "Wilayah",
            "items": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "dataset": "by_region",
                    "x_field": "region",
                    "y_field": "revenue",
                }
            ],
        }
    ],
}


class FakeRunner:
    default_namespace = "db_server"

    def __init__(self):
        self.results = {
            QUERIES["by_region"]: [{"region": "EU", "revenue": 10}],
            QUERIES["total"]: [{"total": 10}],
        }
        self.server_id = "server-db"

    def default_server_id(self):
        return self.server_id

    def run_queries(self, server_id, queries):
        return {
            key: (
                QueryOutcome(rows=self.results[q.sql])
                if q.sql in self.results
                else QueryOutcome(error="no such table")
            )
            for key, q in queries.items()
        }


class TestLiveDashboardSkill(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonLiveDashboardStore(self._tmp.name)
        self.runner = FakeRunner()
        self.hub = LiveDashboardHub()
        self.owner = "user@example.com"
        registry = SkillRegistry()
        registry.load_project_skills([SKILL_DIR])
        registry.bind(
            live_dashboard_store=self.store,
            live_dashboard_runner=self.runner,
            live_dashboard_hub=self.hub,
            live_dashboard_owner_provider=lambda: self.owner,
            live_dashboard_public_base_url="https://chat.example.com/",
        )
        self.tools = {name: fn for name, fn, _schema in registry.collect_tools()}
        self.context = registry.compose_context()
        render_queue.clear()
        self.addCleanup(render_queue.clear)

    def test_discovers_four_tools_and_context(self):
        self.assertEqual(
            set(self.tools),
            {
                "create_live_dashboard",
                "update_live_dashboard",
                "list_live_dashboards",
                "refresh_live_dashboard",
            },
        )
        self.assertIn("db_server.list_tables", self.context)

    def test_create_saves_renders_and_trims_result(self):
        result = self.tools["create_live_dashboard"](
            title="Penjualan",
            queries=QUERIES,
            view_model=VIEW_MODEL,
            refresh_interval_seconds=30,
            public=True,
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["rowCounts"], {"by_region": 1, "total": 1})
        self.assertEqual(result["publicUrl"], f"https://chat.example.com/d/{result['id']}")
        self.assertNotIn("viewModel", result)
        self.assertIn("final_answer_hint", result)

        stored = self.store.get(result["id"])
        self.assertEqual(stored.owner, self.owner)
        self.assertEqual(stored.server_id, "server-db")
        self.assertEqual(stored.refresh_interval_seconds, 30)
        self.assertEqual(stored.version, 1)

        items = render_queue.get_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "dashboard")
        self.assertEqual(items[0]["dashboardId"], result["id"])
        self.assertTrue(items[0]["live"])
        self.assertEqual(items[0]["viewModel"]["kpis"][0]["value"], 10)

    def test_create_reports_query_errors_without_raising(self):
        bad_queries = {**QUERIES, "broken": "SELECT nope FROM missing"}
        view_model = {
            **VIEW_MODEL,
            "kpis": VIEW_MODEL["kpis"] + [{"label": "B", "dataset": "broken", "value_column": "x"}],
        }
        result = self.tools["create_live_dashboard"](
            title="T", queries=bad_queries, view_model=view_model
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(list(result["errors"]), ["broken"])
        self.assertIn("update_live_dashboard", result["final_answer_hint"])

    def test_validation_and_owner_errors(self):
        result = self.tools["create_live_dashboard"](
            title="", queries=QUERIES, view_model=VIEW_MODEL
        )
        self.assertIn("title", result["error"])
        self.owner = None
        result = self.tools["create_live_dashboard"](
            title="T", queries=QUERIES, view_model=VIEW_MODEL
        )
        self.assertIn("owner", result["error"])
        self.owner = "user@example.com"
        self.runner.server_id = None
        result = self.tools["create_live_dashboard"](
            title="T", queries=QUERIES, view_model=VIEW_MODEL
        )
        self.assertIn("db_server", result["error"])

    def test_update_list_refresh_scoped_to_owner(self):
        created = self.tools["create_live_dashboard"](
            title="T", queries=QUERIES, view_model=VIEW_MODEL
        )
        dashboard_id = created["id"]
        listed = self.tools["list_live_dashboards"]()
        self.assertEqual([d["id"] for d in listed["dashboards"]], [dashboard_id])

        updated = self.tools["update_live_dashboard"](
            dashboard_id, refresh_interval_seconds=120, title="Baru"
        )
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(self.store.get(dashboard_id).title, "Baru")
        self.assertEqual(self.store.get(dashboard_id).refresh_interval_seconds, 120)

        self.runner.results[QUERIES["total"]] = [{"total": 77}]
        refreshed = self.tools["refresh_live_dashboard"](dashboard_id)
        self.assertEqual(refreshed["version"], 2)

        bad = self.tools["update_live_dashboard"](dashboard_id, queries={"x": "DROP TABLE t"})
        self.assertIn("read-only", bad["error"])

        self.owner = "other@example.com"
        self.assertEqual(self.tools["list_live_dashboards"]()["dashboards"], [])
        self.assertIn("not found", self.tools["refresh_live_dashboard"](dashboard_id)["error"])


class TestRegistryHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _seed_local(self) -> MCPServerRegistryStore:
        with patch.dict(environ, {"GENERAL_CHAT_MCP_DB_SERVER_CONFIG": "db-server-local.yaml"}):
            seed_all_mcp_registry(self.root, config_dir=CONFIG_DIR)
        return MCPServerRegistryStore(self.root)

    def test_bundled_names_default_and_override(self):
        with patch.dict(environ, {}, clear=False):
            environ.pop("GENERAL_CHAT_MCP_DB_SERVER_CONFIG", None)
            self.assertIn(DEFAULT_DB_SERVER_CONFIG, bundled_mcp_config_names())
            self.assertNotIn("<db-server>", bundled_mcp_config_names())
        with patch.dict(environ, {"GENERAL_CHAT_MCP_DB_SERVER_CONFIG": "db-server-local.yaml"}):
            names = bundled_mcp_config_names()
            self.assertIn("db-server-local.yaml", names)
            self.assertNotIn(DEFAULT_DB_SERVER_CONFIG, names)

    def test_find_server_id_and_open_client(self):
        store = self._seed_local()
        server_id = store.find_server_id(namespace="db_server")
        self.assertIsNotNone(server_id)
        self.assertIsNone(store.find_server_id(namespace="nope"))
        client, namespace = store.open_client(server_id)
        try:
            self.assertEqual(namespace, "db_server")
            self.assertTrue(hasattr(client, "call_tool_sync"))
        finally:
            client.close_sync()
        with self.assertRaises(KeyError):
            store.open_client("server-missing")
        with self.assertRaises(MCPRegistryError):
            store.open_client("internal-openbench")

        store.set_server_enabled(server_id, False)
        self.assertIsNone(store.find_server_id(namespace="db_server"))
        with self.assertRaises(KeyError):
            store.open_client(server_id)


if __name__ == "__main__":
    unittest.main()
