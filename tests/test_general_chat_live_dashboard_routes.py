"""Route tests for live dashboards: REST CRUD, SSE snapshot, public gating."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

pytestmark = pytest.mark.integration

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
                    "title": "Per wilayah",
                    "dataset": "by_region",
                    "x_field": "region",
                    "y_field": "revenue",
                }
            ],
        }
    ],
}


class _FakeClient:
    """Stands in for the db_server MCP: answers execute_sql_json from a row table."""

    rows_by_sql: dict[str, list[dict]] = {}

    def list_tools(self):
        return {"db_server.execute_sql_json": {}, "db_server.execute_sql": {}}

    def call_tool_sync(self, name, arguments=None, **kwargs):
        sql = (arguments or {}).get("sql_query", "")
        rows = self.rows_by_sql.get(sql)
        if rows is None:
            return json.dumps({"error": f"no such table for {sql!r}"})
        return json.dumps({"columns": list(rows[0]) if rows else [], "rows": rows})

    def close_sync(self):
        pass


class TestLiveDashboardRoutes(unittest.TestCase):
    def setUp(self):
        _FakeClient.rows_by_sql = {
            QUERIES["by_region"]: [{"region": "EU", "revenue": 10}, {"region": "US", "revenue": 5}],
            QUERIES["total"]: [{"total": 15}],
        }
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        self.static_dir = self.tmpdir / "static"
        self.static_dir.mkdir()
        (self.static_dir / "index.html").write_text(
            "<!doctype html><title>SPA</title>", encoding="utf-8"
        )
        self.stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(self.tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(self.tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(self.tmpdir / "downloads"),
                    "GENERAL_CHAT_MEMORY_DB": str(self.tmpdir / "memory.db"),
                    "GENERAL_CHAT_STATIC_DIR": str(self.static_dir),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        for key in (
            "GENERAL_CHAT_FIREBASE_PROJECT_ID",
            "GENERAL_CHAT_LOCAL_ROLE",
            "GENERAL_CHAT_LOCAL_GROUP",
            "GENERAL_CHAT_SOURCE_INDEX_ENABLED",
            "GENERAL_CHAT_DATABASE_URL",
        ):
            environ.pop(key, None)
        self.stack.enter_context(
            patch("general_chat.server.app.create_agent", side_effect=lambda **kw: Mock())
        )
        self.stack.enter_context(
            patch(
                "general_chat.mcp_registry.MCPServerRegistryStore.find_server_id",
                return_value="server-db",
            )
        )
        self.stack.enter_context(
            patch(
                "general_chat.mcp_registry.MCPServerRegistryStore.open_client",
                return_value=(_FakeClient(), "db_server"),
            )
        )
        from general_chat.server.app import create_app

        self.app = create_app()
        self.client = TestClient(self.app)

    def _create(self, **overrides) -> dict:
        body = {"title": "Penjualan", "queries": QUERIES, "viewModel": VIEW_MODEL, **overrides}
        response = self.client.post("/dashboard/live", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_runs_queries_and_hydrates(self):
        record = self._create(refreshIntervalSeconds=30)
        self.assertEqual(record["version"], 1)
        self.assertEqual(record["refreshIntervalSeconds"], 30)
        self.assertEqual(record["snapshot"]["viewModel"]["kpis"][0]["value"], 15)
        self.assertEqual(record["serverId"], "server-db")
        self.assertEqual(record["snapshot"]["errors"], {})

        listed = self.client.get("/dashboard/live").json()["dashboards"]
        self.assertEqual([d["id"] for d in listed], [record["id"]])
        self.assertNotIn("snapshot", listed[0])
        self.assertEqual(listed[0]["rowCounts"], {"by_region": 2, "total": 1})

        full = self.client.get(f"/dashboard/live/{record['id']}").json()
        self.assertIn("queries", full)

    def test_create_ignores_caller_server_id(self):
        record = self._create(serverId="server-evil")
        self.assertEqual(record["serverId"], "server-db")

    def test_create_validation_errors(self):
        response = self.client.post(
            "/dashboard/live",
            json={
                "title": "x",
                "queries": {"a": "DROP TABLE t"},
                "viewModel": {"kpis": [{"dataset": "a"}]},
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("read-only", response.json()["detail"])
        self.assertEqual(self.client.post("/dashboard/live", content=b"[]").status_code, 400)

    def test_public_routes_gated_by_flag(self):
        record = self._create()
        dashboard_id = record["id"]
        self.assertEqual(self.client.get(f"/d/{dashboard_id}/data").status_code, 404)
        self.assertEqual(self.client.get(f"/d/{dashboard_id}").status_code, 404)

        patched = self.client.patch(f"/dashboard/live/{dashboard_id}", json={"public": True})
        self.assertEqual(patched.status_code, 200, patched.text)
        payload = self.client.get(f"/d/{dashboard_id}/data").json()
        self.assertEqual(payload["id"], dashboard_id)
        for secret in ("queries", "owner", "serverId", "template"):
            self.assertNotIn(secret, payload)
        self.assertEqual(payload["viewModel"]["kpis"][0]["value"], 15)

        page = self.client.get(f"/d/{dashboard_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("SPA", page.text)

        # Unpublish closes the public surface again.
        self.client.patch(f"/dashboard/live/{dashboard_id}", json={"public": False})
        self.assertEqual(self.client.get(f"/d/{dashboard_id}/data").status_code, 404)

    def test_legacy_published_html_still_served(self):
        response = self.client.post(
            "/dashboard/publish",
            json={"viewModel": {"title": "Static", "kpis": [{"label": "A", "value": 1}]}},
        )
        self.assertEqual(response.status_code, 200)
        dashboard_id = response.json()["id"]
        page = self.client.get(f"/d/{dashboard_id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("SPA", page.text)

    def test_patch_queries_rerun_and_bump_version(self):
        record = self._create()
        _FakeClient.rows_by_sql["SELECT COUNT(*) AS n FROM sales"] = [{"n": 42}]
        response = self.client.patch(
            f"/dashboard/live/{record['id']}",
            json={
                "queries": {"n": "SELECT COUNT(*) AS n FROM sales"},
                "viewModel": {"kpis": [{"label": "Rows", "dataset": "n", "value_column": "n"}]},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["snapshot"]["viewModel"]["kpis"][0]["value"], 42)
        self.assertEqual(list(body["snapshot"]["datasets"]), ["n"])
        bad = self.client.patch(
            f"/dashboard/live/{record['id']}", json={"queries": {"n": "DELETE FROM x"}}
        )
        self.assertEqual(bad.status_code, 400)

    def test_refresh_and_delete(self):
        record = self._create()
        _FakeClient.rows_by_sql[QUERIES["total"]] = [{"total": 99}]
        refreshed = self.client.post(f"/dashboard/live/{record['id']}/refresh")
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json()["version"], 2)
        self.assertEqual(refreshed.json()["viewModel"]["kpis"][0]["value"], 99)

        deleted = self.client.delete(f"/dashboard/live/{record['id']}")
        self.assertEqual(deleted.json(), {"ok": True, "id": record["id"]})
        self.assertEqual(self.client.get(f"/dashboard/live/{record['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"/dashboard/live/{record['id']}").status_code, 404)

    def test_foreign_owner_is_404(self):
        record = self._create()
        store = self.app.state.live_dashboard_store
        stored = store.get(record["id"])
        stored.owner = "someone-else@example.com"
        store.save(stored)
        # Auth disabled -> local caller is admin and may still read it; a
        # plain user must not. Simulate the user role through the local
        # role env the auth middleware honors.
        with patch.dict(environ, {"GENERAL_CHAT_LOCAL_ROLE": "user"}):
            self.assertEqual(self.client.get(f"/dashboard/live/{record['id']}").status_code, 404)
            self.assertEqual(self.client.get("/dashboard/live").json()["dashboards"], [])

    def _close_when_subscribed(self, dashboard_id: str, reason: str) -> threading.Thread:
        """Publish `closed` from another thread once the SSE route has subscribed.

        Starlette's TestClient buffers a streaming body until the generator
        finishes and never reports a client disconnect, so every SSE test
        must end the stream itself -- exactly what a delete/unpublish does
        in production.
        """
        hub = self.app.state.live_dashboard_hub
        from general_chat.live_dashboard import LiveEvent

        def _run():
            deadline = time.time() + 5
            while hub.subscriber_count(dashboard_id) == 0 and time.time() < deadline:
                time.sleep(0.02)
            hub.publish_threadsafe(
                dashboard_id, LiveEvent("closed", {"id": dashboard_id, "reason": reason})
            )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _sse_events(text: str) -> list[tuple[str, dict]]:
        events = []
        for block in text.split("\n\n"):
            lines = [line for line in block.splitlines() if line and not line.startswith(":")]
            if not lines:
                continue
            name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
            data = json.loads(
                next(line[len("data: ") :] for line in lines if line.startswith("data: "))
            )
            events.append((name, data))
        return events

    def test_sse_streams_snapshot_then_closes(self):
        record = self._create()
        hub = self.app.state.live_dashboard_hub
        self._close_when_subscribed(record["id"], "deleted")
        with self.client.stream("GET", f"/dashboard/live/{record['id']}/events") as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
            self.assertEqual(response.headers["x-accel-buffering"], "no")
            events = self._sse_events(response.read().decode("utf-8"))
        self.assertEqual([name for name, _ in events], ["snapshot", "closed"])
        snapshot = events[0][1]
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["viewModel"]["kpis"][0]["value"], 15)
        self.assertNotIn("queries", snapshot)
        self.assertEqual(events[1][1]["reason"], "deleted")
        self.assertEqual(hub.subscriber_count(record["id"]), 0)

    def test_owner_stream_survives_unpublish(self):
        record = self._create(public=True)
        hub = self.app.state.live_dashboard_hub
        from general_chat.live_dashboard import LiveEvent

        def _run():
            deadline = time.time() + 5
            while hub.subscriber_count(record["id"]) == 0 and time.time() < deadline:
                time.sleep(0.02)
            hub.publish_threadsafe(
                record["id"], LiveEvent("closed", {"id": record["id"], "reason": "unpublished"})
            )
            hub.publish_threadsafe(
                record["id"], LiveEvent("update", record and {"id": record["id"], "version": 9})
            )
            hub.publish_threadsafe(
                record["id"], LiveEvent("closed", {"id": record["id"], "reason": "deleted"})
            )

        threading.Thread(target=_run, daemon=True).start()
        with self.client.stream("GET", f"/dashboard/live/{record['id']}/events") as response:
            events = self._sse_events(response.read().decode("utf-8"))
        # The unpublish is swallowed for the owner; the later update still arrives.
        self.assertEqual([name for name, _ in events], ["snapshot", "update", "closed"])
        self.assertEqual(events[2][1]["reason"], "deleted")

    def test_public_sse_requires_public_flag(self):
        record = self._create()
        with self.client.stream("GET", f"/d/{record['id']}/events") as response:
            self.assertEqual(response.status_code, 404)
        self.client.patch(f"/dashboard/live/{record['id']}", json={"public": True})
        self._close_when_subscribed(record["id"], "unpublished")
        with self.client.stream("GET", f"/d/{record['id']}/events") as response:
            self.assertEqual(response.status_code, 200)
            events = self._sse_events(response.read().decode("utf-8"))
        self.assertEqual([name for name, _ in events], ["snapshot", "closed"])
        self.assertNotIn("owner", events[0][1])


if __name__ == "__main__":
    unittest.main()
