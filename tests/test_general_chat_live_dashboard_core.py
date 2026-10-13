"""Unit tests for the general-chat live dashboard core (no server, no MCP)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.live_dashboard import (  # noqa: E402
    JsonLiveDashboardStore,
    LiveDashboardHub,
    LiveDashboardRecord,
    LiveDashboardScheduler,
    LiveDashboardValidationError,
    LiveEvent,
    LiveQuery,
    LiveQueryRunner,
    PostgresLiveDashboardStore,
    QueryOutcome,
    format_sse,
    refresh_record,
    validate_dashboard_input,
)
from general_chat.live_dashboard.models import (  # noqa: E402
    apply_record_changes,
    clamp_refresh_interval,
)
from general_chat.live_dashboard.runner import (  # noqa: E402
    parse_execute_sql_json,
    parse_execute_sql_text,
    tool_result_text,
)
from general_chat.live_dashboard.scheduler import (  # noqa: E402
    compute_data_hash,
    next_run_at,
    select_due,
)
from general_chat.live_dashboard.sqlguard import is_select_only, is_valid_dataset_key  # noqa: E402
from general_chat.server.turn_context import current_turn_owner, set_turn_owner  # noqa: E402

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)

QUERIES = {
    "by_region": "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region",
    "total": {"sql": "SELECT SUM(revenue) AS total FROM sales", "maxRows": 1},
}
TEMPLATE = {
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


def _record(**overrides) -> LiveDashboardRecord:
    validated = validate_dashboard_input(title="Penjualan", queries=QUERIES, view_model=TEMPLATE)
    base = {
        "id": "abcdef123456",
        "owner": "user@example.com",
        "title": validated.title,
        "server_id": "server-1",
        "queries": validated.queries,
        "template": validated.template,
    }
    base.update(overrides)
    return LiveDashboardRecord(**base)


class FakeRunner:
    """Runner stand-in: rows per dataset key, or an error message."""

    def __init__(self, results: dict[str, object]):
        self.results = results
        self.calls: list[tuple[str, list[str]]] = []
        self.default_namespace = "db_server"

    def default_server_id(self):
        return "server-1"

    def run_queries(self, server_id, queries):
        self.calls.append((server_id, list(queries)))
        outcomes = {}
        for key in queries:
            value = self.results.get(key)
            if isinstance(value, str):
                outcomes[key] = QueryOutcome(error=value)
            else:
                outcomes[key] = QueryOutcome(rows=list(value or []))
        return outcomes


class TestSqlGuard(unittest.TestCase):
    def test_accepts_select_and_with(self):
        self.assertTrue(is_select_only("SELECT 1"))
        self.assertTrue(is_select_only("  with t as (select 1) select * from t"))
        self.assertTrue(is_select_only("SELECT a FROM b -- trailing comment"))

    def test_rejects_multi_statement_and_dml(self):
        self.assertFalse(is_select_only("SELECT 1; DROP TABLE x"))
        self.assertFalse(is_select_only("INSERT INTO x VALUES (1)"))
        self.assertFalse(is_select_only("SELECT * INTO y FROM x"))
        self.assertFalse(is_select_only("/* DELETE */ SELECT 1; SELECT 2"))
        self.assertFalse(is_select_only(""))

    def test_comment_cannot_hide_keyword(self):
        self.assertFalse(is_select_only("SELECT 1 /* x */ ; DELETE FROM t"))

    def test_string_literal_cannot_hide_second_statement(self):
        # Stripping "--" first would turn this into a lone "SELECT '" and pass.
        self.assertFalse(is_select_only("SELECT '--'; INSERT INTO t SELECT * FROM s"))
        self.assertFalse(is_select_only("SELECT 1 -- ; DROP TABLE t"))
        self.assertTrue(is_select_only("-- header comment\nSELECT 1"))

    def test_side_effect_functions_rejected(self):
        self.assertFalse(is_select_only("SELECT pg_sleep(10)"))
        self.assertFalse(is_select_only("SELECT pg_read_file('/etc/passwd')"))

    def test_dataset_key_regex(self):
        self.assertTrue(is_valid_dataset_key("by_region2"))
        self.assertFalse(is_valid_dataset_key("By-Region"))
        self.assertFalse(is_valid_dataset_key("1abc"))
        self.assertFalse(is_valid_dataset_key(""))


class TestModels(unittest.TestCase):
    def test_interval_clamping(self):
        self.assertEqual(clamp_refresh_interval(0), 0)
        self.assertEqual(clamp_refresh_interval(-3), 0)
        self.assertEqual(clamp_refresh_interval(7), 15)
        self.assertEqual(clamp_refresh_interval(300), 300)
        self.assertEqual(clamp_refresh_interval(10**9), 86_400)
        with self.assertRaises(LiveDashboardValidationError):
            clamp_refresh_interval("soon")

    def test_validate_strips_datasets_and_keeps_refs(self):
        validated = validate_dashboard_input(
            title="  Penjualan   Harian ",
            queries=QUERIES,
            view_model={**TEMPLATE, "datasets": {"x": []}, "title": "ignored"},
            refresh_interval_seconds=30,
        )
        self.assertEqual(validated.title, "Penjualan Harian")
        self.assertNotIn("datasets", validated.template)
        self.assertNotIn("title", validated.template)
        self.assertEqual(validated.queries["total"].max_rows, 1)
        self.assertEqual(validated.refresh_interval_seconds, 30)

    def test_validate_rejects_unknown_dataset(self):
        bad = {"kpis": [{"label": "X", "dataset": "missing", "value_column": "v"}]}
        with self.assertRaises(LiveDashboardValidationError) as ctx:
            validate_dashboard_input(title="T", queries=QUERIES, view_model=bad)
        self.assertIn("missing", str(ctx.exception))

    def test_validate_rejects_no_panels_and_no_binding(self):
        with self.assertRaises(LiveDashboardValidationError):
            validate_dashboard_input(title="T", queries=QUERIES, view_model={"sections": []})
        static_only = {"kpis": [{"label": "X", "value": 1}]}
        with self.assertRaises(LiveDashboardValidationError):
            validate_dashboard_input(title="T", queries=QUERIES, view_model=static_only)

    def test_validate_rejects_bad_sql_and_too_many(self):
        with self.assertRaises(LiveDashboardValidationError):
            validate_dashboard_input(
                title="T", queries={"a": "DELETE FROM x"}, view_model={"kpis": [{"dataset": "a"}]}
            )
        many = {f"q{i}": "SELECT 1" for i in range(21)}
        with self.assertRaises(LiveDashboardValidationError):
            validate_dashboard_input(
                title="T", queries=many, view_model={"kpis": [{"dataset": "q1"}]}
            )

    def test_public_payload_hides_definition(self):
        record = _record(public=True)
        record.snapshot = {
            "viewModel": {"title": "x", "datasets": {"total": [{"secret": 1}]}, "kpis": []},
            "errors": {"total": "(psycopg) relation hr.salaries does not exist at 10.0.0.5"},
            "refreshedAt": "t",
        }
        record.last_error = "total: relation hr.salaries does not exist"
        payload = record.public_payload()
        for key in ("queries", "owner", "serverId", "template"):
            self.assertNotIn(key, payload)
        # Raw query rows and driver error text never reach viewers.
        self.assertNotIn("datasets", payload["viewModel"])
        self.assertEqual(payload["viewModel"]["title"], "x")
        self.assertEqual(payload["errors"], {"total": "query failed"})
        self.assertEqual(payload["lastError"], "query failed")
        self.assertEqual(payload["refreshedAt"], "t")
        # The owner view keeps the detail.
        self.assertIn("hr.salaries", record.to_dict()["snapshot"]["errors"]["total"])

    def test_round_trip(self):
        record = _record(public=True, version=3)
        clone = LiveDashboardRecord.from_dict(json.loads(json.dumps(record.to_dict())))
        self.assertEqual(clone.queries["total"].sql, record.queries["total"].sql)
        self.assertEqual(clone.template, record.template)
        self.assertTrue(clone.public)
        self.assertEqual(clone.version, 3)

    def test_apply_record_changes(self):
        record = _record()
        changed = apply_record_changes(record, refresh_interval_seconds=120, title="Baru")
        self.assertFalse(changed)
        self.assertEqual(record.refresh_interval_seconds, 120)
        self.assertEqual(record.title, "Baru")
        changed = apply_record_changes(
            record, queries={"only": "SELECT 1 AS v"}, view_model={"kpis": [{"dataset": "only"}]}
        )
        self.assertTrue(changed)
        self.assertEqual(list(record.queries), ["only"])
        # Invalid change leaves the record untouched.
        with self.assertRaises(LiveDashboardValidationError):
            apply_record_changes(record, queries={"bad": "DROP TABLE x"})
        self.assertEqual(list(record.queries), ["only"])


class TestJsonStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonLiveDashboardStore(self._tmp.name)

    def test_crud_and_owner_filter(self):
        a = _record(id="aaaaaaaaaaaa", owner="a@x")
        b = _record(id="bbbbbbbbbbbb", owner="b@x")
        self.store.save(a)
        self.store.save(b)
        self.assertEqual([r.id for r in self.store.list("a@x")], ["aaaaaaaaaaaa"])
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.store.get("bbbbbbbbbbbb").owner, "b@x")
        self.assertIsNone(self.store.get("../etc/passwd"))
        self.assertTrue(self.store.delete("aaaaaaaaaaaa"))
        self.assertFalse(self.store.delete("aaaaaaaaaaaa"))

    def test_corrupt_file_is_skipped(self):
        self.store.save(_record(id="aaaaaaaaaaaa"))
        (self.store._dir / "bbbbbbbbbbbb.json").write_text(
            '{"id": "bbbbbbbbbbbb", "refreshIntervalSeconds": "soon"}', encoding="utf-8"
        )
        (self.store._dir / "cccccccccccc.json").write_text("{not json", encoding="utf-8")
        self.assertEqual([r.id for r in self.store.list()], ["aaaaaaaaaaaa"])
        self.assertEqual(
            [r.id for r in self.store.list_due("2099-01-01T00:00:00+00:00")], ["aaaaaaaaaaaa"]
        )

    def test_list_due(self):
        now_iso = "2026-10-12T08:00:00+00:00"
        due = _record(id="aaaaaaaaaaaa", next_run_at=None)
        later = _record(id="bbbbbbbbbbbb", next_run_at="2026-10-12T09:00:00+00:00")
        manual = _record(id="cccccccccccc", refresh_interval_seconds=0)
        paused = _record(id="dddddddddddd", enabled=False)
        for record in (due, later, manual, paused):
            self.store.save(record)
        self.assertEqual([r.id for r in self.store.list_due(now_iso)], ["aaaaaaaaaaaa"])


class TestPostgresStoreStructure(unittest.TestCase):
    def test_sql_shape(self):
        executed: list[str] = []

        class _Cursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Conn:
            def cursor(self):
                return _Cursor()

            def commit(self):
                pass

        store = PostgresLiveDashboardStore(conn=_Conn())
        joined = "\n".join(executed)
        self.assertIn("openbench_live_dashboards", joined)
        for column in (
            "id TEXT PRIMARY KEY",
            "owner TEXT",
            "is_public BOOLEAN",
            "next_run_at TEXT",
            "config TEXT",
        ):
            self.assertIn(column, joined)
        for method in ("list", "get", "save", "delete", "list_due"):
            self.assertTrue(callable(getattr(store, method)))

    def test_record_from_row(self):
        record = PostgresLiveDashboardStore._record_from_row((json.dumps(_record().to_dict()),))
        self.assertEqual(record.id, "abcdef123456")
        self.assertIsNone(PostgresLiveDashboardStore._record_from_row(("{nope",)))


class TestRunnerParsing(unittest.TestCase):
    def test_tool_result_text_shapes(self):
        self.assertEqual(tool_result_text("abc"), "abc")
        self.assertEqual(tool_result_text({"result": "abc"}), "abc")
        self.assertEqual(
            tool_result_text(
                {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
            ),
            "a\nb",
        )

    def test_parse_json_tool(self):
        payload = json.dumps({"columns": ["r"], "rows": [{"r": 1}], "truncated": True})
        outcome = parse_execute_sql_json(payload)
        self.assertEqual(outcome.rows, [{"r": 1}])
        self.assertTrue(outcome.truncated)
        self.assertEqual(parse_execute_sql_json(json.dumps({"error": "boom"})).error, "boom")
        self.assertIsNotNone(parse_execute_sql_json("not json").error)

    def test_parse_text_table(self):
        text = (
            "SQL Query: SELECT region, revenue FROM t\n\nResults (2 rows):\n"
            "region | revenue | note\n------ | ------- | ----\n"
            "EU | 1200.5 | a | b\nUS | 900 | None\n\n... and 3 more rows\n"
        )
        outcome = parse_execute_sql_text(text)
        self.assertEqual(outcome.columns, ["region", "revenue", "note"])
        self.assertEqual(outcome.rows[0], {"region": "EU", "revenue": 1200.5, "note": "a | b"})
        self.assertEqual(outcome.rows[1], {"region": "US", "revenue": 900, "note": None})
        self.assertTrue(outcome.truncated)

    def test_parse_text_empty_and_error(self):
        self.assertEqual(
            parse_execute_sql_text("SQL Query: x\n\nResults (0 rows):\nNo results found.").rows, []
        )
        self.assertIn("boom", parse_execute_sql_text("Error executing SQL: boom").error)
        self.assertIsNotNone(parse_execute_sql_text("garbage").error)


class _FakeClient:
    def __init__(self, tools, responder):
        self._tools = tools
        self._responder = responder
        self.calls: list[tuple[str, dict]] = []
        self.closed = 0

    def list_tools(self):
        return {name: {} for name in self._tools}

    def call_tool_sync(self, name, arguments=None, **kwargs):
        self.calls.append((name, arguments or {}))
        assert kwargs.get("approved") is True
        return self._responder(name, arguments or {})

    def close_sync(self):
        self.closed += 1


class _FakeRegistry:
    def __init__(self, client, namespace="db_server"):
        self.client = client
        self.namespace = namespace

    def find_server_id(self, *, namespace):
        return "server-1" if namespace == self.namespace else None

    def open_client(self, server_id):
        if server_id != "server-1":
            raise KeyError(server_id)
        return self.client, self.namespace


class TestLiveQueryRunner(unittest.TestCase):
    def test_prefers_json_tool_and_closes_once(self):
        def responder(name, args):
            if "boom" in args["sql_query"]:
                raise RuntimeError("boom")
            return {"result": json.dumps({"columns": ["v"], "rows": [{"v": 1}, {"v": 2}]})}

        client = _FakeClient(["db_server.execute_sql", "db_server.execute_sql_json"], responder)
        runner = LiveQueryRunner(_FakeRegistry(client))
        outcomes = runner.run_queries(
            "server-1",
            {"a": LiveQuery("SELECT 1", max_rows=1), "b": LiveQuery("SELECT boom")},
        )
        self.assertEqual(outcomes["a"].rows, [{"v": 1}])
        self.assertTrue(outcomes["a"].truncated)
        self.assertEqual(outcomes["b"].error, "boom")
        self.assertEqual({name for name, _ in client.calls}, {"db_server.execute_sql_json"})
        self.assertEqual(client.closed, 1)
        self.assertEqual(runner.default_server_id(), "server-1")

    def test_falls_back_to_text_tool(self):
        client = _FakeClient(
            ["db_server.execute_sql"],
            lambda name, args: "SQL Query: q\n\nResults (1 rows):\nv\n-\n7\n",
        )
        outcomes = LiveQueryRunner(_FakeRegistry(client)).run_queries(
            "server-1", {"a": LiveQuery("SELECT 7 AS v")}
        )
        self.assertEqual(outcomes["a"].rows, [{"v": 7}])
        self.assertEqual(client.calls[0][0], "db_server.execute_sql")

    def test_unknown_server_and_missing_tools(self):
        client = _FakeClient(["db_server.list_tables"], lambda n, a: "")
        runner = LiveQueryRunner(_FakeRegistry(client))
        missing = runner.run_queries("server-9", {"a": LiveQuery("SELECT 1")})
        self.assertIn("not registered", missing["a"].error)
        no_tools = runner.run_queries("server-1", {"a": LiveQuery("SELECT 1")})
        self.assertIn("neither", no_tools["a"].error)
        self.assertEqual(client.closed, 1)


class TestHub(unittest.TestCase):
    def test_publish_drop_oldest_and_unsubscribe(self):
        async def scenario():
            hub = LiveDashboardHub(max_queue=2)
            queue = hub.subscribe("d1")
            self.assertEqual(hub.subscriber_count("d1"), 1)
            for i in range(3):
                hub.publish("d1", LiveEvent("update", {"version": i}))
            received = [queue.get_nowait().data["version"], queue.get_nowait().data["version"]]
            self.assertEqual(received, [1, 2])
            hub.unsubscribe("d1", queue)
            self.assertEqual(hub.subscriber_count("d1"), 0)
            self.assertEqual(hub.publish("d1", LiveEvent("update", {})), 0)
            # Unbound hub: publish_threadsafe delivers directly.
            queue2 = hub.subscribe("d2")
            hub.publish_threadsafe("d2", LiveEvent("error", {"error": "x"}))
            self.assertEqual(queue2.get_nowait().type, "error")

        asyncio.run(scenario())

    def test_format_sse(self):
        text = format_sse(LiveEvent("update", {"a": 1}))
        self.assertEqual(text, 'event: update\ndata: {"a": 1}\n\n')


class TestRefreshRecord(unittest.TestCase):
    def test_first_refresh_creates_snapshot_and_event(self):
        runner = FakeRunner(
            {"by_region": [{"region": "EU", "revenue": 5}], "total": [{"total": 5}]}
        )
        record, event = refresh_record(_record(), runner, now=NOW, rand=lambda: 0.0)
        self.assertEqual(event.type, "update")
        self.assertEqual(record.version, 1)
        self.assertEqual(record.snapshot["viewModel"]["kpis"][0]["value"], 5)
        chart = record.snapshot["viewModel"]["sections"][0]["items"][0]
        self.assertEqual(chart["data"], [{"region": "EU", "revenue": 5}])
        self.assertEqual(record.next_run_at, "2026-10-12T08:01:00+00:00")
        self.assertIsNone(record.last_error)
        self.assertEqual(runner.calls[0], ("server-1", ["by_region", "total"]))

    def test_unchanged_data_emits_nothing(self):
        runner = FakeRunner(
            {"by_region": [{"region": "EU", "revenue": 5}], "total": [{"total": 5}]}
        )
        record, _ = refresh_record(_record(), runner, now=NOW)
        record, event = refresh_record(record, runner, now=NOW + timedelta(minutes=1))
        self.assertIsNone(event)
        self.assertEqual(record.version, 1)
        _, forced = refresh_record(record, runner, now=NOW, force=True)
        self.assertEqual(forced.type, "update")
        self.assertEqual(record.version, 1)

    def test_changed_data_bumps_version(self):
        runner = FakeRunner(
            {"by_region": [{"region": "EU", "revenue": 5}], "total": [{"total": 5}]}
        )
        record, _ = refresh_record(_record(), runner, now=NOW)
        runner.results["total"] = [{"total": 9}]
        record, event = refresh_record(record, runner, now=NOW)
        self.assertEqual(event.type, "update")
        self.assertEqual(record.version, 2)
        self.assertEqual(event.data["viewModel"]["kpis"][0]["value"], 9)

    def test_partial_failure_keeps_stale_rows(self):
        runner = FakeRunner(
            {"by_region": [{"region": "EU", "revenue": 5}], "total": [{"total": 5}]}
        )
        record, _ = refresh_record(_record(), runner, now=NOW)
        runner.results["total"] = "syntax error"
        runner.results["by_region"] = [{"region": "EU", "revenue": 6}]
        record, event = refresh_record(record, runner, now=NOW)
        self.assertEqual(event.type, "update")
        self.assertEqual(record.snapshot["datasets"]["total"], [{"total": 5}])
        self.assertEqual(record.snapshot["errors"], {"total": "syntax error"})
        self.assertIsNone(record.last_error)

    def test_total_failure_emits_error_event(self):
        runner = FakeRunner({"by_region": "down", "total": "down"})
        record, event = refresh_record(_record(), runner, now=NOW)
        self.assertEqual(event.type, "error")
        self.assertEqual(record.version, 0)
        self.assertIn("down", record.last_error)
        self.assertIsNotNone(record.next_run_at)

    def test_manual_interval_has_no_next_run(self):
        runner = FakeRunner({"by_region": [], "total": [{"total": 0}]})
        record, _ = refresh_record(_record(refresh_interval_seconds=0), runner, now=NOW)
        self.assertIsNone(record.next_run_at)


class TestSchedulerHelpers(unittest.TestCase):
    def test_next_run_jitter_bounds(self):
        self.assertEqual(next_run_at(60, NOW, rand=lambda: 0.0), "2026-10-12T08:01:00+00:00")
        self.assertEqual(next_run_at(60, NOW, rand=lambda: 1.0), "2026-10-12T08:01:06+00:00")
        self.assertIsNone(next_run_at(0, NOW))

    def test_select_due(self):
        due = _record(id="aaaaaaaaaaaa", next_run_at="2026-10-12T07:59:00+00:00")
        later = _record(id="bbbbbbbbbbbb", next_run_at="2026-10-12T08:00:01+00:00")
        fresh = _record(id="cccccccccccc")
        paused = _record(id="dddddddddddd", enabled=False)
        selected = select_due([due, later, fresh, paused], NOW)
        self.assertEqual([r.id for r in selected], ["aaaaaaaaaaaa", "cccccccccccc"])

    def test_data_hash_is_order_independent(self):
        self.assertEqual(
            compute_data_hash({"a": [1], "b": [2]}), compute_data_hash({"b": [2], "a": [1]})
        )


class TestSchedulerRefresh(unittest.TestCase):
    def test_refresh_saves_and_publishes(self):
        async def scenario():
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            store = JsonLiveDashboardStore(tmp.name)
            store.save(_record())
            runner = FakeRunner(
                {"by_region": [{"region": "EU", "revenue": 1}], "total": [{"total": 1}]}
            )
            hub = LiveDashboardHub()
            hub.bind_loop(asyncio.get_running_loop())
            queue = hub.subscribe("abcdef123456")
            scheduler = LiveDashboardScheduler(store, runner, hub, now_fn=lambda: NOW)

            record = await scheduler.refresh("abcdef123456")
            self.assertEqual(record.version, 1)
            self.assertEqual(store.get("abcdef123456").version, 1)
            self.assertEqual(queue.get_nowait().type, "update")
            self.assertIsNone(await scheduler.refresh("000000000000"))

            # Paused dashboards are skipped unless forced.
            paused = store.get("abcdef123456")
            paused.enabled = False
            store.save(paused)
            self.assertEqual(len(runner.calls), 1)
            await scheduler.refresh("abcdef123456")
            self.assertEqual(len(runner.calls), 1)
            await scheduler.refresh("abcdef123456", force=True)
            self.assertEqual(len(runner.calls), 2)

            # tick() starts refreshes only for due, enabled records.
            paused.enabled = True
            paused.next_run_at = None
            store.save(paused)
            started = await scheduler.tick()
            self.assertEqual(started, 1)
            await asyncio.gather(*scheduler._tasks)
            self.assertEqual(len(runner.calls), 3)

        asyncio.run(scenario())

    def test_refresh_merges_onto_concurrent_edits_and_never_resurrects(self):
        async def scenario():
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            store = JsonLiveDashboardStore(tmp.name)
            store.save(_record(public=True))
            hub = LiveDashboardHub()

            class EditingRunner(FakeRunner):
                """Simulates a PATCH (unpublish + rename) landing while the queries run."""

                def run_queries(self, server_id, queries):
                    edited = store.get("abcdef123456")
                    edited.public = False
                    edited.title = "Diganti"
                    store.save(edited)
                    return super().run_queries(server_id, queries)

            runner = EditingRunner(
                {"by_region": [{"region": "EU", "revenue": 1}], "total": [{"total": 1}]}
            )
            scheduler = LiveDashboardScheduler(store, runner, hub, now_fn=lambda: NOW)
            record = await scheduler.refresh("abcdef123456")
            self.assertFalse(record.public)  # the unpublish survived
            self.assertEqual(record.title, "Diganti")
            self.assertEqual(record.version, 1)  # the fresh snapshot was applied
            self.assertEqual(store.get("abcdef123456").public, False)

            class DeletingRunner(FakeRunner):
                def run_queries(self, server_id, queries):
                    store.delete("abcdef123456")
                    return super().run_queries(server_id, queries)

            scheduler = LiveDashboardScheduler(
                store,
                DeletingRunner({"by_region": [], "total": [{"total": 0}]}),
                hub,
                now_fn=lambda: NOW,
            )
            self.assertIsNone(await scheduler.refresh("abcdef123456"))
            self.assertIsNone(store.get("abcdef123456"))  # not resurrected

            class RedefiningRunner(FakeRunner):
                def run_queries(self, server_id, queries):
                    edited = store.get("abcdef123456")
                    edited.queries = {"only": LiveQuery("SELECT 1 AS v")}
                    store.save(edited)
                    return super().run_queries(server_id, queries)

            store.save(_record())
            scheduler = LiveDashboardScheduler(
                store,
                RedefiningRunner(
                    {"by_region": [{"region": "EU", "revenue": 1}], "total": [{"total": 1}]}
                ),
                hub,
                now_fn=lambda: NOW,
            )
            record = await scheduler.refresh("abcdef123456")
            self.assertEqual(list(record.queries), ["only"])
            self.assertEqual(record.version, 0)  # stale snapshot dropped
            self.assertIsNone(record.next_run_at)  # due again on the next tick

        asyncio.run(scenario())

    def test_refresh_exception_advances_schedule(self):
        async def scenario():
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            store = JsonLiveDashboardStore(tmp.name)
            store.save(_record())

            class BrokenRunner(FakeRunner):
                def run_queries(self, server_id, queries):
                    raise RuntimeError("registry exploded")

            scheduler = LiveDashboardScheduler(
                store, BrokenRunner({}), LiveDashboardHub(), now_fn=lambda: NOW
            )
            record = await scheduler.refresh("abcdef123456")
            self.assertIn("registry exploded", record.last_error)
            self.assertIsNotNone(record.next_run_at)
            self.assertEqual(store.get("abcdef123456").next_run_at, record.next_run_at)

        asyncio.run(scenario())


class TestTurnContext(unittest.TestCase):
    def test_owner_visible_in_worker_thread(self):
        async def scenario():
            set_turn_owner("me@example.com")
            seen = await asyncio.to_thread(current_turn_owner)
            self.assertEqual(seen, "me@example.com")
            set_turn_owner(None)
            self.assertIsNone(current_turn_owner())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
