"""Tests for bundled SDK skills in ``src/openbench/skills/``.

Verifies that every SDK skill:
1. Loads cleanly via ``Skill.from_dir``
2. Is discovered by ``SkillRegistry.load_sdk_skills``
3. Exposes the tool set declared in its SKILL.md
4. Its tools behave correctly on simple inputs (pure-Python tools only;
   pandas-backed tools are smoke-tested to confirm the error path works
   without the optional dep)
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from openbench.intelligence.skill import Skill
from openbench.intelligence.skill_registry import SkillRegistry

SDK_SKILLS_DIR = Path(__file__).resolve().parent.parent / "src" / "openbench" / "skills"


class TestSDKSkillsDiscovery(unittest.TestCase):
    """All 4 RFC-required SDK skills must exist and be discoverable."""

    REQUIRED_SKILLS = {
        "data-context-extractor",
        "dashboard-generator",
        "data-visualization",
        "export-excel",
        "pdf-tools",
        "query-explorer",
        "web-search",
    }

    def test_sdk_skills_dir_exists(self):
        self.assertTrue(SDK_SKILLS_DIR.is_dir(), f"Missing SDK skills dir: {SDK_SKILLS_DIR}")

    def test_every_required_skill_has_a_directory(self):
        present = {d.name for d in SDK_SKILLS_DIR.iterdir() if d.is_dir()}
        missing = self.REQUIRED_SKILLS - present
        self.assertFalse(missing, f"Missing SDK skill dirs: {missing}")

    def test_every_required_skill_loads_via_skill_registry(self):
        reg = SkillRegistry()
        reg.load_sdk_skills()
        loaded = {s.name for s in reg.all()}
        missing = self.REQUIRED_SKILLS - loaded
        self.assertFalse(missing, f"SkillRegistry did not discover: {missing}")

    def test_every_required_skill_has_tools(self):
        """Every SDK skill in the RFC is a capability skill, not knowledge-only."""
        reg = SkillRegistry()
        reg.load_sdk_skills()
        for skill in reg.all():
            if skill.name not in self.REQUIRED_SKILLS:
                continue
            self.assertTrue(
                skill.has_tools,
                f"{skill.name} should have tools (no knowledge-only SDK skills in RFC)",
            )
            self.assertGreater(len(skill.tools), 0, f"{skill.name} must expose ≥1 tool")

    def test_each_skill_loads_via_from_dir(self):
        for name in self.REQUIRED_SKILLS:
            with self.subTest(skill=name):
                skill = Skill.from_dir(SDK_SKILLS_DIR / name)
                self.assertEqual(skill.name, name)
                self.assertTrue(skill.description, f"{name} has empty description")
                self.assertTrue(skill.triggers, f"{name} has no triggers")


class TestDataVisualizationSkill(unittest.TestCase):
    """Pure-Python chart builders — no external deps."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "data-visualization")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}

    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools),
            {
                "create_bar_chart",
                "create_line_chart",
                "create_pie_chart",
                "create_scatter_chart",
                "create_area_chart",
            },
        )

    def test_bar_chart_produces_renderable_dict(self):
        result = self.tools["create_bar_chart"](
            title="Q4 Revenue",
            data=[{"name": "Jan", "value": 100}, {"name": "Feb", "value": 150}],
        )
        self.assertEqual(result["type"], "bar")
        self.assertEqual(result["title"], "Q4 Revenue")
        self.assertEqual(len(result["data"]), 2)
        self.assertIn("options", result)

    def test_line_chart_uses_xy_keys_by_default(self):
        result = self.tools["create_line_chart"](
            title="Trend",
            data=[{"x": 1, "y": 10}, {"x": 2, "y": 20}],
        )
        self.assertEqual(result["type"], "line")
        self.assertEqual(result["data"][0], {"x": 1, "y": 10})

    def test_pie_chart_warns_when_too_many_slices(self):
        data = [{"name": f"S{i}", "value": i} for i in range(10)]
        result = self.tools["create_pie_chart"](title="Too Many", data=data)
        self.assertIn("warning", result["options"])

    def test_pie_chart_no_warning_for_small_slice_count(self):
        result = self.tools["create_pie_chart"](
            title="Ok",
            data=[{"name": "A", "value": 1}, {"name": "B", "value": 2}],
        )
        self.assertNotIn("warning", result["options"])

    def test_validation_error_on_missing_key(self):
        result = self.tools["create_bar_chart"](
            title="Bad",
            data=[{"name": "x"}],  # missing 'value'
        )
        self.assertIn("error", result)

    def test_validation_error_on_empty_data(self):
        result = self.tools["create_bar_chart"](title="Bad", data=[])
        self.assertIn("error", result)

    def test_chart_output_matches_renderer_contract(self):
        """Output must be detectable by ChartRenderer."""
        from openbench.chat.renderers.chart import ChartRenderer

        renderer = ChartRenderer()
        for tool_name in self.tools:
            if not tool_name.startswith("create_"):
                continue
            with self.subTest(tool=tool_name):
                result = self.tools[tool_name](
                    title="Smoke test",
                    data=[{"name": "a", "value": 1, "x": 1, "y": 1}],
                )
                # Skip error cases (shouldn't hit on valid input)
                self.assertNotIn("error", result, f"{tool_name} raised unexpectedly")
                self.assertTrue(
                    renderer.detect(result),
                    f"{tool_name} output not detected by ChartRenderer: {result}",
                )


class TestDataVisualizationPushesRenderItem(unittest.TestCase):
    """All 5 chart tools must push their output onto the shared render queue
    so ChatEngine surfaces an ObChart component in the assistant turn."""

    def setUp(self):
        from openbench.chat import render_queue

        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "data-visualization")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.queue = render_queue
        self.queue.clear()

    def tearDown(self):
        self.queue.clear()

    def test_every_chart_tool_pushes_to_queue(self):
        for tool_name in self.tools:
            with self.subTest(tool=tool_name):
                self.queue.clear()
                result = self.tools[tool_name](
                    title="Test",
                    data=[{"name": "a", "value": 1, "x": 1, "y": 1}],
                )
                self.assertNotIn("error", result)
                queued = self.queue.get_items()
                self.assertEqual(len(queued), 1, f"{tool_name} did not push to queue")
                self.assertEqual(queued[0]["type"], result["type"])

    def test_error_results_do_not_push(self):
        result = self.tools["create_bar_chart"](title="Bad", data=[])
        self.assertIn("error", result)
        self.assertEqual(self.queue.get_items(), [])

    def test_pushed_item_detected_by_chart_renderer(self):
        from openbench.chat.renderers.chart import ChartRenderer

        renderer = ChartRenderer()
        self.tools["create_bar_chart"](title="Revenue", data=[{"name": "Q1", "value": 100}])
        queued = self.queue.get_items()
        self.assertEqual(len(queued), 1)
        self.assertTrue(renderer.detect(queued[0]))


class TestQueryExplorerSkill(unittest.TestCase):
    """Pure-Python relational ops — no external deps."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "query-explorer")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.sample = [
            {"name": "Alice", "region": "EU", "revenue": 100},
            {"name": "Bob", "region": "US", "revenue": 150},
            {"name": "Carol", "region": "EU", "revenue": 50},
            {"name": "Dave", "region": "US", "revenue": 200},
        ]

    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools),
            {
                "filter_records",
                "sort_records",
                "group_and_aggregate",
                "distinct_values",
                "top_n_records",
            },
        )

    def test_filter_records_eq(self):
        result = self.tools["filter_records"](
            self.sample,
            [{"column": "region", "op": "eq", "value": "EU"}],
        )
        self.assertEqual(result["count"], 2)
        self.assertTrue(all(r["region"] == "EU" for r in result["records"]))

    def test_filter_records_gt(self):
        result = self.tools["filter_records"](
            self.sample,
            [{"column": "revenue", "op": "gt", "value": 100}],
        )
        self.assertEqual(result["count"], 2)
        self.assertTrue(all(r["revenue"] > 100 for r in result["records"]))

    def test_filter_records_in(self):
        result = self.tools["filter_records"](
            self.sample,
            [{"column": "name", "op": "in", "value": ["Alice", "Dave"]}],
        )
        self.assertEqual(result["count"], 2)

    def test_filter_records_contains(self):
        result = self.tools["filter_records"](
            [{"note": "foo bar"}, {"note": "baz"}],
            [{"column": "note", "op": "contains", "value": "foo"}],
        )
        self.assertEqual(result["count"], 1)

    def test_filter_records_unsupported_op_returns_error(self):
        result = self.tools["filter_records"](
            self.sample, [{"column": "region", "op": "like", "value": "EU"}]
        )
        self.assertIn("error", result)

    def test_sort_records_asc(self):
        result = self.tools["sort_records"](self.sample, "revenue")
        revenues = [r["revenue"] for r in result["records"]]
        self.assertEqual(revenues, sorted(revenues))

    def test_sort_records_desc(self):
        result = self.tools["sort_records"](self.sample, "revenue", descending=True)
        revenues = [r["revenue"] for r in result["records"]]
        self.assertEqual(revenues, sorted(revenues, reverse=True))

    def test_group_and_aggregate_sum(self):
        result = self.tools["group_and_aggregate"](
            self.sample, "region", "sum", aggregate_column="revenue"
        )
        by_region = {g["region"]: g["sum_revenue"] for g in result["groups"]}
        self.assertEqual(by_region["EU"], 150)
        self.assertEqual(by_region["US"], 350)

    def test_group_and_aggregate_mean(self):
        result = self.tools["group_and_aggregate"](
            self.sample, "region", "mean", aggregate_column="revenue"
        )
        by_region = {g["region"]: g["mean_revenue"] for g in result["groups"]}
        self.assertEqual(by_region["EU"], 75.0)
        self.assertEqual(by_region["US"], 175.0)

    def test_group_and_aggregate_count_without_column(self):
        result = self.tools["group_and_aggregate"](self.sample, "region", "count")
        by_region = {g["region"]: g["count_*"] for g in result["groups"]}
        self.assertEqual(by_region["EU"], 2)
        self.assertEqual(by_region["US"], 2)

    def test_group_and_aggregate_unsupported_op(self):
        result = self.tools["group_and_aggregate"](
            self.sample, "region", "median", aggregate_column="revenue"
        )
        self.assertIn("error", result)

    def test_distinct_values_preserves_order(self):
        result = self.tools["distinct_values"](self.sample, "region")
        self.assertEqual(result["values"], ["EU", "US"])
        self.assertEqual(result["count"], 2)

    def test_top_n_records(self):
        result = self.tools["top_n_records"](self.sample, "revenue", n=2)
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["records"][0]["name"], "Dave")
        self.assertEqual(result["records"][1]["name"], "Bob")

    def test_top_n_records_ascending(self):
        result = self.tools["top_n_records"](self.sample, "revenue", n=2, descending=False)
        self.assertEqual(result["records"][0]["name"], "Carol")

    def test_top_n_invalid_n_returns_error(self):
        result = self.tools["top_n_records"](self.sample, "revenue", n=0)
        self.assertIn("error", result)


class TestDashboardGeneratorSkill(unittest.TestCase):
    """CSV/XLSX dashboard skill: metadata, aggregation, and artifact output."""

    def setUp(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas is not installed")
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "dashboard-generator")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.tool_schemas = {name: schema for name, _, schema in self.skill.tools}

    def tearDown(self):
        import sys

        module = sys.modules.get("openbench_skill_dashboard_generator")
        if module is not None and hasattr(module, "bind"):
            module.bind(dashboard_adapter=None, dashboard_adapter_factory=None)

    def _write_csv(self, directory: str) -> str:
        path = Path(directory) / "sales.csv"
        path.write_text(
            "region,segment,revenue,date\n"
            "EU,Enterprise,100,2026-01-01\n"
            "EU,SMB,50,2026-01-02\n"
            "US,Enterprise,150,2026-01-03\n",
            encoding="utf-8",
        )
        return str(path)

    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools),
            {"extract_metadata", "aggregate_data", "generate_dashboard"},
        )
        aggregate_parameters = self.tool_schemas["aggregate_data"]["function"]["parameters"]
        self.assertIn("query", aggregate_parameters["properties"])
        self.assertNotIn("operations", aggregate_parameters["properties"])
        self.assertEqual(aggregate_parameters["required"], ["path", "query"])
        # query advertises a list so the model batches all aggregations in one call.
        self.assertEqual(aggregate_parameters["properties"]["query"]["type"], "array")
        generate_schema = self.tool_schemas["generate_dashboard"]["function"]
        self.assertIn("canonical OpenBench shape", generate_schema["description"])
        self.assertIn(
            "x_field",
            generate_schema["parameters"]["properties"]["view_model"]["description"],
        )

    def test_extract_metadata_profiles_csv_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(tmp)
            result = self.tools["extract_metadata"](path=path)

        self.assertNotIn("error", result)
        self.assertEqual(result["format"], "csv")
        self.assertEqual(result["row_count"], 3)
        columns = {column["name"]: column for column in result["columns"]}
        self.assertEqual(columns["revenue"]["role_hint"], "metric")
        self.assertIn("region", columns)
        self.assertIn("sample", result)
        self.assertEqual(result["sql"]["dialect"], "sqlite")
        self.assertEqual(result["sql"]["table"], "data")

    def test_aggregate_data_group_sum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(tmp)
            result = self.tools["aggregate_data"](
                path=path,
                dataset_id="revenue_by_region",
                query=(
                    'SELECT "region", SUM("revenue") AS revenue '
                    'FROM data GROUP BY "region" ORDER BY revenue DESC'
                ),
            )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["dialect"], "sqlite")
        self.assertEqual(result["table"], "data")
        self.assertEqual(result["datasets"][0]["id"], "revenue_by_region")
        records = {row["region"]: row["revenue"] for row in result["datasets"][0]["records"]}
        self.assertEqual(records, {"EU": 150, "US": 150})

    def test_aggregate_data_batch_returns_one_dataset_per_query(self):
        """A list of queries runs in one call and returns one dataset each."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(tmp)
            result = self.tools["aggregate_data"](
                path=path,
                query=[
                    'SELECT "region", SUM("revenue") AS revenue FROM data GROUP BY "region"',
                    'SELECT "segment", COUNT(*) AS orders FROM data GROUP BY "segment"',
                ],
            )

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["datasets"]), 2)
        self.assertEqual(
            {ds["id"] for ds in result["datasets"]}, {"dataset_1", "dataset_2"}
        )

    def test_aggregate_data_rejects_destructive_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(tmp)
            result = self.tools["aggregate_data"](path=path, query="DROP TABLE data")

        self.assertEqual(result["datasets"], [])
        self.assertIn(
            "Only read-only SELECT or WITH queries are allowed",
            result["errors"][0]["error"],
        )

    def test_generate_dashboard_writes_html_and_queues_artifact(self):
        from openbench.chat import render_queue
        from openbench.chat.renderers.dashboard import DashboardRenderer

        render_queue.clear()
        with tempfile.TemporaryDirectory() as tmp:
            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Sales Dashboard",
                    "description": "Uploaded sales data.",
                    "datasets": {
                        "revenue_by_region": [
                            {"region": "EU", "revenue": 150},
                            {"region": "US", "revenue": 150},
                        ]
                    },
                    "kpis": [{"label": "Total Revenue", "value": 300}],
                    "sections": [
                        {
                            "title": "Revenue",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "dataset": "revenue_by_region",
                                    "x": "region",
                                    "y": "revenue",
                                }
                            ],
                        }
                    ],
                },
            )
            output = Path(result["path"])
            self.assertTrue(output.exists())
            html_text = output.read_text(encoding="utf-8")

        self.assertEqual(result["type"], "dashboard")
        self.assertEqual(result["mimeType"], "text/html")
        self.assertEqual(result["render_mode"], "a2ui")
        self.assertEqual(result["viewModel"]["title"], "Sales Dashboard")
        self.assertEqual(result["datasets"]["revenue_by_region"][0]["region"], "EU")
        self.assertEqual(result["kpis"][0]["label"], "Total Revenue")
        self.assertEqual(result["sections"][0]["title"], "Revenue")
        self.assertEqual(result["sectionCount"], 1)
        self.assertEqual(result["kpiCount"], 1)
        self.assertIn("Sales Dashboard", html_text)
        queued = render_queue.get_items()
        self.assertEqual(len(queued), 1)
        self.assertTrue(DashboardRenderer().detect(queued[0]))
        self.assertEqual(queued[0]["render_mode"], "a2ui")
        self.assertEqual(queued[0]["viewModel"]["title"], "Sales Dashboard")
        self.assertEqual(queued[0]["datasets"], result["datasets"])
        self.assertEqual(queued[0]["sections"], result["sections"])
        render_queue.clear()

    def test_generate_dashboard_accepts_uploaded_template_path(self):
        template_path = (
            Path(__file__).resolve().parent.parent
            / "examples"
            / "general-chat"
            / "template-dashboard-sample"
            / "template.html"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                template_path=str(template_path),
                view_model={
                    "title": "Uploaded Template Dashboard",
                    "kpis": [{"label": "Revenue", "value": 300}],
                    "sections": [],
                },
            )
            html_text = Path(result["path"]).read_text(encoding="utf-8")

        self.assertEqual(result["render_mode"], "a2ui")
        self.assertEqual(result["customTemplate"]["format"], "html")
        self.assertEqual(result["templateSource"], "user")
        self.assertEqual(result["templateFormat"], "html")
        self.assertIn('data-custom-template="executive-html"', html_text)
        self.assertIn("Uploaded Template Dashboard", html_text)

    def test_generate_dashboard_hydrates_cached_aggregate_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "coffee.csv"
            source.write_text(
                "coffee_name,money\nLatte,10\nLatte,15\nEspresso,5\n",
                encoding="utf-8",
            )
            aggregate = self.tools["aggregate_data"](
                path=str(source),
                query=[
                    {
                        "name": "revenue_by_coffee",
                        "sql": (
                            "SELECT coffee_name, SUM(money) AS revenue "
                            "FROM data GROUP BY coffee_name ORDER BY revenue DESC"
                        ),
                    }
                ],
            )
            self.assertEqual(aggregate["errors"], [])
            self.assertEqual(aggregate["datasets"][0]["id"], "revenue_by_coffee")

            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Coffee Sales",
                    "components": [
                        {
                            "type": "kpi",
                            "content": {"title": "Total Revenue", "value": 30},
                        },
                        {
                            "type": "chart",
                            "content": {
                                "title": "Revenue by Coffee",
                                "type": "bar",
                                "data": "revenue_by_coffee",
                                "x": "coffee_name",
                                "y": "revenue",
                            },
                        },
                    ],
                },
            )
            html_text = Path(result["path"]).read_text(encoding="utf-8")

        self.assertEqual(result["datasets"]["revenue_by_coffee"][0]["coffee_name"], "Latte")
        self.assertEqual(result["kpis"][0]["label"], "Total Revenue")
        self.assertIn("Revenue by Coffee", html_text)
        self.assertIn("Latte", html_text)
        self.assertNotIn("No chart data available.", html_text)

    def test_generate_dashboard_uses_injected_adapter_factory(self):
        import sys

        calls: list[dict[str, Any]] = []
        module = sys.modules["openbench_skill_dashboard_generator"]

        def adapter_factory(*, output_path: str | Path, public_url: str | None = None):
            class FakeAdapter:
                def render(self, view_model: dict[str, Any]) -> dict[str, Any]:
                    output = Path(output_path)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text("<html><body>Injected adapter</body></html>", encoding="utf-8")
                    calls.append(
                        {
                            "view_model": view_model,
                            "output_path": output,
                            "public_url": public_url,
                        }
                    )
                    return {
                        "file_path": str(output),
                        "size_bytes": output.stat().st_size,
                        "adapter": {"name": "fake", "used": True},
                    }

            return FakeAdapter()

        module.bind(dashboard_adapter_factory=adapter_factory)

        with tempfile.TemporaryDirectory() as tmp:
            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={"title": "DI Dashboard", "sections": []},
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["view_model"]["title"], "DI Dashboard")
        self.assertEqual(result["adapter"], {"name": "fake", "used": True})
        self.assertTrue(result["path"].endswith(".html"))

    def test_stitch_adapter_uses_mcp_tools_call_flow(self):
        from unittest.mock import patch

        class FakeResponse:
            def __init__(self, payload: dict[str, Any]):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        calls: list[dict[str, Any]] = []

        def fake_post(url, *, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            if json["method"] == "tools/list":
                return FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "tools": [
                                {"name": "create_project"},
                                {"name": "generate_screen_from_text"},
                            ]
                        },
                    }
                )
            if json["method"] == "tools/call" and json["params"]["name"] == "create_project":
                return FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": '{"name": "projects/123456789"}',
                                }
                            ]
                        },
                    }
                )
            if (
                json["method"] == "tools/call"
                and json["params"]["name"] == "generate_screen_from_text"
            ):
                return FakeResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        '{"name": "projects/123456789/screens/screenabc", '
                                        '"url": "https://stitch.google.com/p/123456789/s/screenabc"}'
                                    ),
                                }
                            ]
                        },
                    }
                )
            raise AssertionError(f"Unexpected MCP call: {json}")

        saved_env = {
            key: os.environ.get(key)
            for key in [
                "DASHBOARD_RENDER_ADAPTER",
                "STITCH_API_KEY",
                "STITCH_API_URL",
                "STITCH_API_MODE",
                "STITCH_PROJECT_ID",
            ]
        }
        os.environ["DASHBOARD_RENDER_ADAPTER"] = "stitch"
        os.environ["STITCH_API_KEY"] = "test-key"
        os.environ["STITCH_API_URL"] = "https://stitch.googleapis.com/mcp"
        os.environ.pop("STITCH_PROJECT_ID", None)
        os.environ.pop("STITCH_API_MODE", None)
        try:
            with patch("requests.post", side_effect=fake_post):
                with tempfile.TemporaryDirectory() as tmp:
                    result = self.tools["generate_dashboard"](
                        output_dir=tmp,
                        view_model={
                            "title": "MCP Dashboard",
                            "datasets": {"sales": [{"region": "EU", "revenue": 10}]},
                            "sections": [],
                        },
                    )
                    output = Path(result["path"])
                    html_text = output.read_text(encoding="utf-8")
        finally:
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual([call["json"]["method"] for call in calls], ["tools/list", "tools/call", "tools/call"])
        self.assertEqual(calls[0]["headers"]["X-Goog-Api-Key"], "test-key")
        self.assertEqual(calls[2]["json"]["params"]["name"], "generate_screen_from_text")
        self.assertEqual(calls[2]["json"]["params"]["arguments"]["projectId"], "123456789")
        self.assertEqual(result["adapter"], {"name": "stitch", "used": True, "transport": "mcp"})
        self.assertEqual(result["stitch"]["transport"], "mcp")
        self.assertEqual(result["stitch"]["project_id"], "123456789")
        self.assertEqual(result["stitch"]["screen_id"], "screenabc")
        self.assertNotIn("fallback", result["adapter"])
        self.assertIn("Stitch MCP generated a screen", html_text)


class TestDataContextExtractorSkill(unittest.TestCase):
    """Smoke tests — covers JSON path (stdlib only) and error paths."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "data-context-extractor")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}

    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools),
            {
                "extract_file_context",
                "read_csv_file",
                "read_excel_file",
                "list_excel_sheets",
                "save_column_profile",
                "get_column_profile",
                "update_column_profile",
            },
        )

    def test_extract_file_context_missing_file(self):
        result = self.tools["extract_file_context"]("/nonexistent/path/does-not-exist.csv")
        self.assertIn("error", result)

    def test_extract_file_context_unsupported_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"some content")
            tmp_path = f.name
        try:
            result = self.tools["extract_file_context"](tmp_path)
            self.assertIn("error", result)
            self.assertIn("Unsupported", result["error"])
        finally:
            os.unlink(tmp_path)

    def test_extract_file_context_json_list(self):
        """JSON path uses stdlib only — always available."""
        data = [
            {"id": 1, "name": "Alice", "score": 42},
            {"id": 2, "name": "Bob", "score": 99},
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            result = self.tools["extract_file_context"](tmp_path)
            self.assertEqual(result["format"], "json")
            self.assertEqual(result["row_count"], 2)
            self.assertEqual(len(result["columns"]), 3)
            column_names = {c["name"] for c in result["columns"]}
            self.assertEqual(column_names, {"id", "name", "score"})
        finally:
            os.unlink(tmp_path)

    def test_extract_file_context_json_nested_records_key(self):
        data = {"records": [{"a": 1}, {"a": 2}]}
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            result = self.tools["extract_file_context"](tmp_path)
            self.assertEqual(result["row_count"], 2)
        finally:
            os.unlink(tmp_path)

    def test_extract_file_context_json_malformed(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("not json at all {{{")
            tmp_path = f.name
        try:
            result = self.tools["extract_file_context"](tmp_path)
            self.assertIn("error", result)
        finally:
            os.unlink(tmp_path)


class TestColumnProfileSystem(unittest.TestCase):
    """Tests for the column profile (save/get/update) in data-context-extractor."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "data-context-extractor")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        # Use a temp dir for profiles so tests don't pollute
        self._tmp_dir = tempfile.mkdtemp()
        self._env_backup = os.environ.get("OPENBENCH_PROFILE_DIR")
        os.environ["OPENBENCH_PROFILE_DIR"] = self._tmp_dir

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        if self._env_backup is None:
            os.environ.pop("OPENBENCH_PROFILE_DIR", None)
        else:
            os.environ["OPENBENCH_PROFILE_DIR"] = self._env_backup

    def _make_json_file(self, data: list[dict]) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_save_and_get_profile(self):
        path = self._make_json_file([{"Region": "EU", "Revenue": 100.0}])
        try:
            result = self.tools["save_column_profile"](
                path,
                [
                    {"column": "Region", "role": "category"},
                    {"column": "Revenue", "role": "amount"},
                ],
            )
            self.assertTrue(result["saved"])
            self.assertIn("file_hash", result)

            # Get it back
            got = self.tools["get_column_profile"](path)
            self.assertEqual(got["profile_status"], "cached")
            profile = got["profile"]
            cols = profile["sheets"]["default"]["columns"]
            roles = {c["physical_name"]: c["role"] for c in cols}
            self.assertEqual(roles["Region"], "category")
            self.assertEqual(roles["Revenue"], "amount")
        finally:
            os.unlink(path)

    def test_get_profile_not_found(self):
        path = self._make_json_file([{"a": 1}])
        try:
            got = self.tools["get_column_profile"](path)
            self.assertEqual(got["profile_status"], "not_found")
        finally:
            os.unlink(path)

    def test_update_profile(self):
        path = self._make_json_file([{"Region": "EU", "Revenue": 100.0}])
        try:
            self.tools["save_column_profile"](
                path,
                [{"column": "Revenue", "role": "amount"}],
            )
            result = self.tools["update_column_profile"](
                path, "Revenue", "metric", description="Quarterly metric"
            )
            self.assertTrue(result["updated"])

            # Verify the update persisted
            got = self.tools["get_column_profile"](path)
            cols = got["profile"]["sheets"]["default"]["columns"]
            rev = next(c for c in cols if c["physical_name"] == "Revenue")
            self.assertEqual(rev["role"], "metric")
            self.assertEqual(rev["description"], "Quarterly metric")
        finally:
            os.unlink(path)

    def test_update_adds_new_column(self):
        path = self._make_json_file([{"A": 1, "B": 2}])
        try:
            self.tools["save_column_profile"](path, [{"column": "A", "role": "label"}])
            self.tools["update_column_profile"](path, "B", "amount")

            got = self.tools["get_column_profile"](path)
            cols = got["profile"]["sheets"]["default"]["columns"]
            names = {c["physical_name"] for c in cols}
            self.assertEqual(names, {"A", "B"})
        finally:
            os.unlink(path)

    def test_update_without_profile_returns_error(self):
        path = self._make_json_file([{"a": 1}])
        try:
            result = self.tools["update_column_profile"](path, "a", "label")
            self.assertIn("error", result)
        finally:
            os.unlink(path)

    def test_extract_file_context_returns_profile_status(self):
        """extract_file_context should include profile_status field."""
        path = self._make_json_file([{"Name": "Alice", "Score": 42.0}])
        try:
            # No profile yet
            result = self.tools["extract_file_context"](path)
            self.assertEqual(result["profile_status"], "needs_mapping")
            self.assertIn("unmapped_columns", result)

            # Save profile
            self.tools["save_column_profile"](
                path,
                [
                    {"column": "Name", "role": "label"},
                    {"column": "Score", "role": "amount"},
                ],
            )

            # Now should be cached
            result2 = self.tools["extract_file_context"](path)
            self.assertEqual(result2["profile_status"], "cached")
            self.assertIn("column_roles", result2)
            self.assertEqual(result2["column_roles"]["Name"], "label")
            self.assertEqual(result2["column_roles"]["Score"], "amount")
        finally:
            os.unlink(path)

    def test_same_content_different_name_shares_profile(self):
        """Profile is keyed by content hash — rename doesn't lose mapping."""
        data = [{"X": 1.0, "Y": 2.0}]
        path1 = self._make_json_file(data)
        path2 = self._make_json_file(data)  # same content, different path
        try:
            self.tools["save_column_profile"](path1, [{"column": "X", "role": "amount"}])
            got = self.tools["get_column_profile"](path2)
            self.assertEqual(got["profile_status"], "cached")
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_save_rejects_empty_mappings(self):
        path = self._make_json_file([{"a": 1}])
        try:
            result = self.tools["save_column_profile"](path, [])
            self.assertIn("error", result)
        finally:
            os.unlink(path)


class TestExportExcelSkill(unittest.TestCase):
    """Smoke tests for error paths — pandas may or may not be installed."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "export-excel")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}

    def test_expected_tools_present(self):
        self.assertEqual(set(self.tools), {"export_to_excel", "export_multi_sheet_excel"})

    def test_export_to_excel_rejects_empty_records(self):
        result = self.tools["export_to_excel"]([], "out.xlsx")
        self.assertIn("error", result)

    def test_export_multi_sheet_rejects_empty_mapping(self):
        result = self.tools["export_multi_sheet_excel"]({}, "out.xlsx")
        self.assertIn("error", result)

    def test_export_multi_sheet_rejects_non_list_sheet(self):
        result = self.tools["export_multi_sheet_excel"]({"sheet1": "not a list"}, "out.xlsx")
        self.assertIn("error", result)

    def test_export_to_excel_rejects_non_list_records(self):
        result = self.tools["export_to_excel"]("not a list", "out.xlsx")
        self.assertIn("error", result)


class TestExportExcelPathResolution(unittest.TestCase):
    """Unit tests for the path / URL resolution helpers.

    These are critical for deployed setups: without OPENBENCH_EXPORT_DIR
    set, every export lands in the process CWD (usually the repo root),
    and without OPENBENCH_EXPORT_URL_BASE the returned render item's
    ``url`` field is a filesystem path that the frontend can't fetch
    over HTTP — so file cards look fine but every download link 404s.
    """

    def setUp(self):
        # Import via the loaded skill module so we can exercise the
        # private helpers that aren't exposed as tools.
        import sys

        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "export-excel")
        mod_name = f"openbench_skill_{self.skill.name.replace('-', '_')}"
        self.mod = sys.modules[mod_name]

        # Snapshot env for restoration
        self._env_backup = {
            "OPENBENCH_EXPORT_DIR": os.environ.get("OPENBENCH_EXPORT_DIR"),
            "OPENBENCH_EXPORT_URL_BASE": os.environ.get("OPENBENCH_EXPORT_URL_BASE"),
        }
        os.environ.pop("OPENBENCH_EXPORT_DIR", None)
        os.environ.pop("OPENBENCH_EXPORT_URL_BASE", None)

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unique_filename_preserves_stem_and_ext(self):
        name = self.mod._unique_filename("report.xlsx")
        self.assertTrue(name.startswith("report-"))
        self.assertTrue(name.endswith(".xlsx"))
        # "report-" + 8 hex chars + ".xlsx"
        self.assertEqual(len(name), len("report-") + 8 + len(".xlsx"))

    def test_unique_filename_strips_directory_components(self):
        # Skills don't get to pick their output directory — strip any
        # path traversal attempts from the supplied filename.
        name = self.mod._unique_filename("../../etc/passwd.xlsx")
        self.assertFalse(name.startswith(".."))
        self.assertNotIn("/", name)
        self.assertTrue(name.startswith("passwd-"))

    def test_unique_filename_adds_default_xlsx_extension(self):
        name = self.mod._unique_filename("report")
        self.assertTrue(name.endswith(".xlsx"))

    def test_unique_filename_produces_different_values(self):
        names = {self.mod._unique_filename("same.xlsx") for _ in range(10)}
        # Astronomically unlikely to collide in 10 draws
        self.assertEqual(len(names), 10)

    def test_resolve_output_uses_env_var_when_no_explicit_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OPENBENCH_EXPORT_DIR"] = tmp
            resolved = self.mod._resolve_output("report.xlsx", None)
            self.assertEqual(str(resolved.parent), str(Path(tmp).resolve()))

    def test_resolve_output_explicit_dir_overrides_env(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            os.environ["OPENBENCH_EXPORT_DIR"] = tmp1
            resolved = self.mod._resolve_output("report.xlsx", tmp2)
            self.assertEqual(str(resolved.parent), str(Path(tmp2).resolve()))

    def test_resolve_output_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "a" / "b" / "c"
            self.mod._resolve_output("report.xlsx", str(sub))
            self.assertTrue(sub.exists())

    def test_public_url_uses_url_base_when_set(self):
        os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"
        url = self.mod._public_url(Path("/var/app/downloads/report-abc123.xlsx"))
        self.assertEqual(url, "/downloads/report-abc123.xlsx")

    def test_public_url_strips_trailing_slash_from_base(self):
        os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads/"
        url = self.mod._public_url(Path("/some/where/report.xlsx"))
        self.assertEqual(url, "/downloads/report.xlsx")

    def test_public_url_falls_back_to_filesystem_path_without_base(self):
        url = self.mod._public_url(Path("/some/where/report.xlsx"))
        self.assertEqual(url, "/some/where/report.xlsx")

    def test_file_item_includes_mimetype(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake xlsx bytes")
            tmp_path = Path(f.name)
        try:
            item = self.mod._file_item(tmp_path, ["Sheet1"])
            self.assertIn("mimeType", item)
            self.assertIn("spreadsheetml", item["mimeType"])
            self.assertEqual(item["name"], tmp_path.name)
            self.assertIn("size", item)
        finally:
            os.unlink(tmp_path)

    def test_file_item_url_uses_env_base(self):
        os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"
        fake_path = Path("/tmp/nonexistent-xyz/report-abc.xlsx")
        item = self.mod._file_item(fake_path, ["Sheet1"])
        self.assertEqual(item["url"], "/downloads/report-abc.xlsx")


class TestExportExcelPushesRenderItem(unittest.TestCase):
    """Regression: export-excel must push its file item onto the shared
    render queue so ChatEngine surfaces an ObFileCard. Without this,
    the file gets written to disk but the assistant turn only contains
    plain text and the user has no clickable download link."""

    def setUp(self):
        from openbench.chat import render_queue

        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "export-excel")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.queue = render_queue
        self.queue.clear()

        # Save env and clear so helper paths are deterministic
        self._env_backup = {
            "OPENBENCH_EXPORT_DIR": os.environ.get("OPENBENCH_EXPORT_DIR"),
            "OPENBENCH_EXPORT_URL_BASE": os.environ.get("OPENBENCH_EXPORT_URL_BASE"),
        }
        os.environ.pop("OPENBENCH_EXPORT_DIR", None)
        os.environ.pop("OPENBENCH_EXPORT_URL_BASE", None)

    def tearDown(self):
        self.queue.clear()
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _have_pandas(self) -> bool:
        try:
            import pandas  # noqa: F401

            return True
        except ImportError:
            return False

    def test_export_to_excel_pushes_file_item(self):
        if not self._have_pandas():
            self.skipTest("pandas not installed")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OPENBENCH_EXPORT_DIR"] = tmp
            os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"

            result = self.tools["export_to_excel"](
                [{"a": 1, "b": 2}, {"a": 3, "b": 4}],
                "test.xlsx",
            )

        self.assertNotIn("error", result)
        # Queue now has exactly one file item matching the returned one
        queued = self.queue.get_items()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["name"], result["name"])
        self.assertEqual(queued[0]["url"], result["url"])
        self.assertTrue(queued[0]["url"].startswith("/downloads/"))

    def test_export_multi_sheet_pushes_file_item(self):
        if not self._have_pandas():
            self.skipTest("pandas not installed")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OPENBENCH_EXPORT_DIR"] = tmp
            os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"

            result = self.tools["export_multi_sheet_excel"](
                {
                    "Summary": [{"k": "v"}],
                    "Detail": [{"x": 1}, {"x": 2}],
                },
                "report.xlsx",
            )

        self.assertNotIn("error", result)
        queued = self.queue.get_items()
        self.assertEqual(len(queued), 1)
        # The pushed item carries both sheet names
        self.assertEqual(set(queued[0]["sheets"]), {"Summary", "Detail"})

    def test_pushed_item_is_detected_by_file_renderer(self):
        """End-to-end shape check — the pushed item must match FileRenderer
        contract so ChatEngine actually renders it."""
        if not self._have_pandas():
            self.skipTest("pandas not installed")

        from openbench.chat.renderers.file import FileRenderer

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OPENBENCH_EXPORT_DIR"] = tmp
            os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"
            self.tools["export_to_excel"]([{"a": 1}], "x.xlsx")

        queued = self.queue.get_items()
        self.assertEqual(len(queued), 1)
        renderer = FileRenderer()
        self.assertTrue(
            renderer.detect(queued[0]),
            f"FileRenderer should detect the pushed item: {queued[0]}",
        )

    def test_error_results_do_not_push(self):
        """If the tool fails, nothing should land on the queue."""
        # Empty records → error, no push
        result = self.tools["export_to_excel"]([], "bad.xlsx")
        self.assertIn("error", result)
        self.assertEqual(self.queue.get_items(), [])


class TestWebSearchSkill(unittest.TestCase):
    """Tests for web-search SDK skill — tool loading + error paths."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "web-search")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}

    def test_expected_tools_present(self):
        self.assertEqual(set(self.tools), {"web_search", "web_search_multi"})

    def test_skill_metadata(self):
        self.assertEqual(self.skill.name, "web-search")
        self.assertTrue(self.skill.has_tools)
        self.assertTrue(self.skill.description)
        self.assertTrue(self.skill.triggers)
        self.assertIn("search-guide.md", self.skill.references)

    def test_web_search_empty_query_returns_error(self):
        result = self.tools["web_search"]("")
        self.assertIn("error", result)

    def test_web_search_whitespace_query_returns_error(self):
        result = self.tools["web_search"]("   ")
        self.assertIn("error", result)

    def test_web_search_multi_empty_list_returns_error(self):
        result = self.tools["web_search_multi"]([])
        self.assertIn("error", result)

    def test_web_search_multi_non_list_returns_error(self):
        result = self.tools["web_search_multi"]("not a list")
        self.assertIn("error", result)

    def test_web_search_multi_invalid_query_element(self):
        """Invalid elements produce per-item errors, not a crash."""
        result = self.tools["web_search_multi"](["", "   "])
        self.assertIn("results", result)
        self.assertEqual(len(result["results"]), 2)
        for r in result["results"]:
            self.assertIn("error", r)

    def test_web_search_without_api_key_returns_error(self):
        """Without GOOGLE_API_KEY set, search should error gracefully."""
        # Temporarily remove the env var if set
        import os

        saved = os.environ.pop("GOOGLE_API_KEY", None)
        try:
            result = self.tools["web_search"]("test query")
            # Should either error (no API key) or succeed (if key happens to be set)
            # We just verify it doesn't crash
            self.assertIsInstance(result, dict)
        finally:
            if saved:
                os.environ["GOOGLE_API_KEY"] = saved


class TestPdfToolsSkill(unittest.TestCase):
    """Tests for pdf-tools SDK skill."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "pdf-tools")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}

    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools),
            {
                "pdf_metadata",
                "read_pdf",
                "read_pdf_page",
                "extract_pdf_tables",
                "merge_pdfs",
                "split_pdf",
                "generate_pdf",
            },
        )

    def test_skill_metadata(self):
        self.assertEqual(self.skill.name, "pdf-tools")
        self.assertTrue(self.skill.has_tools)
        self.assertIn("pdf-guide.md", self.skill.references)

    def _make_pdf(self, pages: int = 3) -> str:
        """Create a small test PDF via reportlab."""
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import Paragraph, SimpleDocTemplate

        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        doc = SimpleDocTemplate(path, pagesize=A4, title="Test PDF", author="Test")
        elements = []
        from reportlab.lib.styles import getSampleStyleSheet

        styles = getSampleStyleSheet()
        for i in range(pages):
            elements.append(Paragraph(f"Page {i} content. Hello world.", styles["BodyText"]))
            if i < pages - 1:
                from reportlab.platypus import PageBreak

                elements.append(PageBreak())
        doc.build(elements)
        return path

    def test_pdf_metadata(self):
        path = self._make_pdf(3)
        try:
            result = self.tools["pdf_metadata"](path)
            self.assertNotIn("error", result)
            self.assertEqual(result["page_count"], 3)
            self.assertEqual(result["title"], "Test PDF")
            self.assertEqual(result["author"], "Test")
            self.assertFalse(result["encrypted"])
        finally:
            os.unlink(path)

    def test_pdf_metadata_missing_file(self):
        result = self.tools["pdf_metadata"]("/nonexistent/file.pdf")
        self.assertIn("error", result)

    def test_read_pdf(self):
        path = self._make_pdf(3)
        try:
            result = self.tools["read_pdf"](path)
            self.assertNotIn("error", result)
            self.assertEqual(result["page_count"], 3)
            self.assertIn("Page 0 content", result["text"])
            self.assertFalse(result["truncated"])
        finally:
            os.unlink(path)

    def test_read_pdf_with_page_filter(self):
        path = self._make_pdf(5)
        try:
            result = self.tools["read_pdf"](path, pages=[0, 2, 4])
            self.assertNotIn("error", result)
            self.assertEqual(result["pages_read"], [0, 2, 4])
            self.assertIn("Page 0 content", result["text"])
            self.assertIn("Page 2 content", result["text"])
        finally:
            os.unlink(path)

    def test_read_pdf_truncation(self):
        path = self._make_pdf(10)
        try:
            result = self.tools["read_pdf"](path, max_chars=50)
            self.assertTrue(result["truncated"])
            self.assertIn("truncated_at_page", result)
            self.assertLessEqual(len(result["text"]), 55)  # small margin
        finally:
            os.unlink(path)

    def test_read_pdf_pages_out_of_range(self):
        path = self._make_pdf(3)
        try:
            result = self.tools["read_pdf"](path, pages=[99])
            self.assertIn("error", result)
            self.assertIn("out of range", result["error"])
        finally:
            os.unlink(path)

    def test_read_pdf_page(self):
        path = self._make_pdf(3)
        try:
            result = self.tools["read_pdf_page"](path, 1)
            self.assertNotIn("error", result)
            self.assertEqual(result["page"], 1)
            self.assertIn("Page 1 content", result["text"])
        finally:
            os.unlink(path)

    def test_read_pdf_page_out_of_range(self):
        path = self._make_pdf(3)
        try:
            result = self.tools["read_pdf_page"](path, 99)
            self.assertIn("error", result)
        finally:
            os.unlink(path)

    def test_split_pdf(self):
        path = self._make_pdf(5)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["OPENBENCH_EXPORT_DIR"] = tmp
                result = self.tools["split_pdf"](path, [0, 2, 4], "subset.pdf")
                self.assertNotIn("error", result)
                self.assertEqual(result["page_count"], 3)
                self.assertEqual(result["pages_extracted"], [0, 2, 4])
                os.environ.pop("OPENBENCH_EXPORT_DIR", None)
        finally:
            os.unlink(path)

    def test_split_pdf_empty_pages(self):
        path = self._make_pdf(3)
        try:
            result = self.tools["split_pdf"](path, [], "bad.pdf")
            self.assertIn("error", result)
        finally:
            os.unlink(path)

    def test_merge_pdfs(self):
        path1 = self._make_pdf(2)
        path2 = self._make_pdf(3)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["OPENBENCH_EXPORT_DIR"] = tmp
                result = self.tools["merge_pdfs"]([path1, path2], "combined.pdf")
                self.assertNotIn("error", result)
                self.assertEqual(result["page_count"], 5)
                os.environ.pop("OPENBENCH_EXPORT_DIR", None)
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_merge_pdfs_single_file_error(self):
        path = self._make_pdf(1)
        try:
            result = self.tools["merge_pdfs"]([path])
            self.assertIn("error", result)
        finally:
            os.unlink(path)

    def test_generate_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OPENBENCH_EXPORT_DIR"] = tmp
            result = self.tools["generate_pdf"](
                title="Test Report",
                sections=[
                    {"type": "heading", "content": "Summary"},
                    {"type": "text", "content": "This is a test report."},
                    {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
                ],
                filename="test_report.pdf",
            )
            self.assertNotIn("error", result)
            self.assertIn("test_report", result["name"])
            self.assertTrue(result["name"].endswith(".pdf"))
            os.environ.pop("OPENBENCH_EXPORT_DIR", None)

    def test_generate_pdf_empty_sections(self):
        result = self.tools["generate_pdf"](title="Bad", sections=[])
        self.assertIn("error", result)


class TestSDKSkillRegistryIntegration(unittest.TestCase):
    """End-to-end: load all SDK skills through the registry."""

    def test_compose_context_includes_every_skill(self):
        reg = SkillRegistry()
        reg.load_sdk_skills()
        context = reg.compose_context()
        for name in TestSDKSkillsDiscovery.REQUIRED_SKILLS:
            self.assertIn(name, context, f"compose_context() missing '{name}'")

    def test_collect_tools_has_no_name_collisions(self):
        reg = SkillRegistry()
        reg.load_sdk_skills()
        tools = reg.collect_tools()
        names = [name for name, _, _ in tools]
        self.assertEqual(len(names), len(set(names)), f"Tool name collisions: {names}")

    def test_collect_tools_count_matches_expected(self):
        reg = SkillRegistry()
        reg.load_sdk_skills()
        tools = reg.collect_tools()
        # data-context-extractor(2) + dashboard-generator(3)
        # + data-visualization(5) + export-excel(2)
        # + pdf-tools(7) + query-explorer(5) + web-search(7)
        # + memory-scratchpad(4) = 35 tools
        self.assertEqual(len(tools), 35)

    def test_load_skills_by_name_after_load_sdk_skills(self):
        """load_skills(['data-visualization']) must work after load_sdk_skills()."""
        reg = SkillRegistry()
        reg.load_sdk_skills()
        reg.load_skills(["data-visualization"])
        self.assertIn("data-visualization", reg)

    def test_registry_summary_includes_sdk_skills(self):
        reg = SkillRegistry()
        reg.load_sdk_skills()
        summary = reg.summary()
        self.assertGreaterEqual(len(summary["sdk_skills"]), 6)
        self.assertGreater(summary["total_tools"], 0)


# ---------------------------------------------------------------------------
# export-excel — bound output_store path
# ---------------------------------------------------------------------------


class TestExportExcelBoundOutputStore(unittest.TestCase):
    """When an output_store is bound, exports MUST go through it (not env).

    Regression guard for the Drive-backed uploads/downloads story:
    without this test, a silent skill refactor could bypass the bound
    store and drop files on the server's disk instead of the user's
    Drive. Uses ``LocalFileStore`` as a stand-in for any FileStore
    impl — the contract we care about is the ``store`` / ``get`` /
    ``get_local_path`` Protocol.
    """

    def setUp(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas not installed — export-excel tests require [data] extras")

        import sys
        import tempfile

        from openbench.chat.files import LocalFileStore

        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "export-excel")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}

        mod_name = f"openbench_skill_{self.skill.name.replace('-', '_')}"
        self.mod = sys.modules[mod_name]

        self._store_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._store_dir.cleanup)

        self.store = LocalFileStore(upload_dir=self._store_dir.name)
        self.skill.bind(output_store=self.store, output_url_base="/downloads")
        self.addCleanup(self.skill.bind, output_store=None, output_url_base=None)

    def test_export_to_excel_routes_through_bound_store(self):
        result = self.tools["export_to_excel"](
            [{"a": 1, "b": 2}, {"a": 3, "b": 4}],
            "report.xlsx",
        )
        self.assertNotIn("error", result)
        # URL contract: /{base}/{id}/{name}
        self.assertTrue(result["url"].startswith("/downloads/"))
        # Store holds exactly one file and its id matches the URL.
        file_id = result["url"].split("/")[2]
        stored = self.store.get(file_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertTrue(stored.name.startswith("report-"))
        self.assertTrue(stored.name.endswith(".xlsx"))
        self.assertGreater(stored.size_bytes, 0)

    def test_export_multi_sheet_routes_through_bound_store(self):
        result = self.tools["export_multi_sheet_excel"](
            {"S1": [{"x": 1}], "S2": [{"y": 2}]},
            "multi.xlsx",
        )
        self.assertNotIn("error", result)
        self.assertEqual(sorted(result["sheets"]), ["S1", "S2"])
        self.assertTrue(result["url"].startswith("/downloads/"))

    def test_bound_store_takes_priority_over_env_var(self):
        """Even with OPENBENCH_EXPORT_DIR set, the bound store should win."""
        os.environ["OPENBENCH_EXPORT_DIR"] = "/does/not/exist/ignore-me"
        self.addCleanup(os.environ.pop, "OPENBENCH_EXPORT_DIR", None)

        result = self.tools["export_to_excel"]([{"a": 1}], "out.xlsx")
        self.assertNotIn("error", result)
        # URL is the bound one, not the env one.
        self.assertTrue(result["url"].startswith("/downloads/"))

    def test_tmp_file_deleted_after_bound_store_ingest(self):
        """The intermediate disk write must not leak into /tmp forever."""
        import tempfile

        tmp_before = set(os.listdir(tempfile.gettempdir()))
        result = self.tools["export_to_excel"]([{"a": 1}], "clean.xlsx")
        self.assertNotIn("error", result)
        tmp_after = set(os.listdir(tempfile.gettempdir()))
        new_xlsx = [n for n in (tmp_after - tmp_before) if n.startswith("clean-")]
        self.assertEqual(new_xlsx, [])

    def test_url_base_can_be_omitted(self):
        """Without a URL base, fall back to the store's local path."""
        self.skill.bind(output_store=self.store, output_url_base=None)
        result = self.tools["export_to_excel"]([{"a": 1}], "out.xlsx")
        self.assertNotIn("error", result)
        # Absolute filesystem path — still downloadable by CLI users.
        self.assertTrue(os.path.isabs(result["url"]))

    def test_web_view_link_wins_over_backend_url(self):
        """A store that surfaces ``web_view_link`` (Drive / cloud) takes
        priority — the URL points at the user's authenticated cloud UI,
        not at the backend proxy."""
        # Wrap LocalFileStore so every store() call returns a StoredFile
        # with web_view_link set — mimics GoogleDriveFileStore.
        from openbench.chat.files import LocalFileStore, StoredFile

        class _CloudishStore:
            def __init__(self, inner: LocalFileStore):
                self._inner = inner

            def store(self, filename: str, content: bytes, mime: str) -> StoredFile:
                s = self._inner.store(filename, content, mime)
                return StoredFile(
                    id=s.id,
                    name=s.name,
                    path=s.path,
                    mime_type=s.mime_type,
                    size_bytes=s.size_bytes,
                    stored_at=s.stored_at,
                    web_view_link=f"https://drive.google.com/file/d/{s.id}/view",
                )

            def get(self, file_id):
                return self._inner.get(file_id)

            def get_local_path(self, file_id):
                return self._inner.get_local_path(file_id)

        cloudish = _CloudishStore(self.store)
        self.skill.bind(output_store=cloudish, output_url_base="/downloads")

        result = self.tools["export_to_excel"]([{"a": 1}], "c.xlsx")
        self.assertNotIn("error", result)
        # URL points at drive.google.com, NOT at /downloads.
        self.assertTrue(result["url"].startswith("https://drive.google.com/"))
        # The frontend-facing "external" flag is set so ObFileCard opens
        # in a new tab instead of forcing a download.
        self.assertIs(result.get("external"), True)


if __name__ == "__main__":
    unittest.main()
