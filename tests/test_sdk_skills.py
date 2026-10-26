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

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

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
        "source-retrieval",
        "table-query",
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
        self._memory_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._memory_dir.cleanup)
        self._old_dashboard_memory_db = os.environ.get("OPENBENCH_DASHBOARD_MEMORY_DB")
        self._old_dashboard_memory_enabled = os.environ.get("OPENBENCH_DASHBOARD_MEMORY_ENABLED")
        self._old_dashboard_state_path = os.environ.get("OPENBENCH_DASHBOARD_STATE_PATH")
        os.environ["OPENBENCH_DASHBOARD_MEMORY_DB"] = str(
            Path(self._memory_dir.name) / "dashboard_memory.db"
        )
        os.environ["OPENBENCH_DASHBOARD_STATE_PATH"] = str(
            Path(self._memory_dir.name) / "dashboard_generator_state.json"
        )
        os.environ["OPENBENCH_DASHBOARD_MEMORY_ENABLED"] = "1"
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "dashboard-generator")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.tool_schemas = {name: schema for name, _, schema in self.skill.tools}

    def tearDown(self):
        import sys

        module = sys.modules.get("openbench_skill_dashboard_generator")
        if module is not None and hasattr(module, "bind"):
            module.bind(
                dashboard_adapter=None,
                dashboard_adapter_factory=None,
                dashboard_memory_db_path=None,
            )
        if self._old_dashboard_memory_db is None:
            os.environ.pop("OPENBENCH_DASHBOARD_MEMORY_DB", None)
        else:
            os.environ["OPENBENCH_DASHBOARD_MEMORY_DB"] = self._old_dashboard_memory_db
        if self._old_dashboard_memory_enabled is None:
            os.environ.pop("OPENBENCH_DASHBOARD_MEMORY_ENABLED", None)
        else:
            os.environ["OPENBENCH_DASHBOARD_MEMORY_ENABLED"] = self._old_dashboard_memory_enabled
        if self._old_dashboard_state_path is None:
            os.environ.pop("OPENBENCH_DASHBOARD_STATE_PATH", None)
        else:
            os.environ["OPENBENCH_DASHBOARD_STATE_PATH"] = self._old_dashboard_state_path

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
            {
                "extract_metadata",
                "aggregate_data",
                "generate_dashboard",
                "load_dashboard_memory",
            },
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
        self.assertIn("previous_dashboard_id", generate_schema["parameters"]["properties"])
        self.assertIn("revision_panel_titles", generate_schema["parameters"]["properties"])
        self.assertIn(
            "source_signature",
            self.tool_schemas["load_dashboard_memory"]["function"]["parameters"]["properties"],
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
        self.assertIn("source_signature", result)
        self.assertEqual(result["dashboard_memory"]["matches"], [])
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
        self.assertEqual({ds["id"] for ds in result["datasets"]}, {"dataset_1", "dataset_2"})

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
        self.assertIn("dashboardId", result)
        self.assertTrue(result["memory"]["persisted"])
        self.assertIn("Sales Dashboard", html_text)
        queued = render_queue.get_items()
        self.assertEqual(len(queued), 1)
        self.assertTrue(DashboardRenderer().detect(queued[0]))
        self.assertEqual(queued[0]["render_mode"], "a2ui")
        self.assertEqual(queued[0]["viewModel"]["title"], "Sales Dashboard")
        self.assertEqual(queued[0]["datasets"], result["datasets"])
        self.assertEqual(queued[0]["sections"], result["sections"])
        self.assertEqual(result["chartCount"], 1)
        self.assertEqual(result["tableCount"], 0)
        self.assertEqual(result["warnings"], [])
        render_queue.clear()

    def test_generate_dashboard_surfaces_invalid_item_warnings(self):
        from openbench.chat import render_queue

        render_queue.clear()
        with tempfile.TemporaryDirectory() as tmp:
            # Bare integers as section items (invented dataset references) —
            # the tool must report them so the calling agent can self-correct
            # instead of retrying blind.
            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Coffee Sales Dashboard",
                    "kpis": [{"label": "Total Revenue", "value": 115431.58}],
                    "sections": [
                        {"title": "Sales Trends", "items": [6]},
                        {"title": "Product Analysis", "items": [8]},
                    ],
                },
            )

        self.assertEqual(result["type"], "dashboard")
        self.assertEqual(result["chartCount"], 0)
        self.assertTrue(result["warnings"], "expected warnings for invalid section items")
        self.assertIn("int", result["warnings"][0])
        # Warnings are lifted out of the viewModel so the UI payload stays clean.
        self.assertNotIn("normalization_warnings", result["viewModel"])
        render_queue.clear()

    def test_dashboard_memory_loads_previous_dashboard_for_same_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(tmp)
            metadata = self.tools["extract_metadata"](path=path)
            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                source_path=path,
                view_model={
                    "title": "Consistent Sales Dashboard",
                    "sections": [
                        {
                            "title": "Revenue",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue by Region",
                                    "data": [{"region": "EU", "revenue": 150}],
                                    "x_field": "region",
                                    "y_field": "revenue",
                                }
                            ],
                        }
                    ],
                },
            )

            loaded = self.tools["load_dashboard_memory"](source_path=path)
            metadata_after = self.tools["extract_metadata"](path=path)

        self.assertEqual(metadata["source_signature"], loaded["source_signature"])
        self.assertEqual(loaded["count"], 1)
        self.assertEqual(loaded["records"][0]["dashboard_id"], result["dashboardId"])
        self.assertEqual(
            loaded["records"][0]["viewModel"]["sections"][0]["items"][0]["title"],
            "Revenue by Region",
        )
        self.assertEqual(
            metadata_after["dashboard_memory"]["matches"][0]["dashboard_id"],
            result["dashboardId"],
        )

    def test_dashboard_revision_preserves_unspecified_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Sales Dashboard",
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "pie",
                                    "title": "Revenue Share",
                                    "data": [{"region": "EU", "revenue": 150}],
                                    "x_field": "region",
                                    "y_field": "revenue",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "line",
                                    "title": "Revenue Trend",
                                    "data": [{"date": "2026-01-01", "revenue": 100}],
                                    "x_field": "date",
                                    "y_field": "revenue",
                                },
                            ],
                        }
                    ],
                },
            )
            revised = self.tools["generate_dashboard"](
                output_dir=tmp,
                previous_dashboard_id=first["dashboardId"],
                revision_notes="Change Revenue Share from pie to bar.",
                revision_panel_titles=["Revenue Share"],
                view_model={
                    "title": "Sales Dashboard",
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue Share",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue Trend",
                                    "data": [{"date": "2026-02-01", "revenue": 999}],
                                    "x_field": "date",
                                    "y_field": "revenue",
                                },
                            ],
                        }
                    ],
                },
            )

        items = revised["viewModel"]["sections"][0]["items"]
        self.assertEqual(len(items), 2)
        by_title = {item["title"]: item for item in items}
        self.assertEqual(by_title["Revenue Share"]["chart_type"], "bar")
        self.assertEqual(by_title["Revenue Share"]["x_field"], "region")
        self.assertEqual(by_title["Revenue Trend"]["chart_type"], "line")
        self.assertEqual(by_title["Revenue Trend"]["data"][0]["revenue"], 100)
        self.assertEqual(revised["revisionOf"], first["dashboardId"])
        self.assertEqual(revised["revisionMerge"]["applied_keys"], ["revenue share"])

    def test_dashboard_revision_rejects_ambiguous_multi_panel_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Sales Dashboard",
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "pie",
                                    "title": "Revenue Share",
                                    "data": [{"region": "EU", "revenue": 150}],
                                    "x_field": "region",
                                    "y_field": "revenue",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "line",
                                    "title": "Revenue Trend",
                                    "data": [{"date": "2026-01-01", "revenue": 100}],
                                    "x_field": "date",
                                    "y_field": "revenue",
                                },
                            ],
                        }
                    ],
                },
            )
            revised = self.tools["generate_dashboard"](
                output_dir=tmp,
                previous_dashboard_id=first["dashboardId"],
                revision_notes="Change one chart as requested.",
                view_model={
                    "title": "Sales Dashboard",
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue Share",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue Trend",
                                    "data": [{"date": "2026-02-01", "revenue": 999}],
                                    "x_field": "date",
                                    "y_field": "revenue",
                                },
                            ],
                        }
                    ],
                },
            )

        by_title = {item["title"]: item for item in revised["viewModel"]["sections"][0]["items"]}
        self.assertEqual(by_title["Revenue Share"]["chart_type"], "pie")
        self.assertEqual(by_title["Revenue Trend"]["chart_type"], "line")
        self.assertEqual(revised["revisionMerge"]["applied_keys"], [])
        self.assertTrue(revised["revisionMerge"]["strict_panel_merge"])

    def test_dashboard_revision_preserves_unrelated_top_level_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Sales Dashboard",
                    "datasets": {
                        "share": [{"region": "EU", "revenue": 150}],
                        "trend": [{"date": "2026-01-01", "revenue": 100}],
                    },
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "pie",
                                    "title": "Revenue Share",
                                    "dataset": "share",
                                    "x_field": "region",
                                    "y_field": "revenue",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "line",
                                    "title": "Revenue Trend",
                                    "dataset": "trend",
                                    "x_field": "date",
                                    "y_field": "revenue",
                                },
                            ],
                        }
                    ],
                },
            )
            revised = self.tools["generate_dashboard"](
                output_dir=tmp,
                previous_dashboard_id=first["dashboardId"],
                revision_notes="Change Revenue Share from pie to bar.",
                revision_panel_titles=["Revenue Share"],
                view_model={
                    "title": "Sales Dashboard",
                    "datasets": {
                        "share": [{"region": "EU", "revenue": 200}],
                        "trend": [{"date": "2026-02-01", "revenue": 999}],
                    },
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue Share",
                                    "dataset": "share",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue Trend",
                                    "dataset": "trend",
                                },
                            ],
                        }
                    ],
                },
            )

        self.assertEqual(revised["datasets"]["share"][0]["revenue"], 200)
        self.assertEqual(revised["datasets"]["trend"][0]["revenue"], 100)
        by_title = {item["title"]: item for item in revised["viewModel"]["sections"][0]["items"]}
        self.assertEqual(by_title["Revenue Share"]["chart_type"], "bar")
        self.assertEqual(by_title["Revenue Trend"]["chart_type"], "line")

    def test_dashboard_auto_revision_preserves_unrequested_noncanonical_panel_changes(self):
        title = "Coffee Sales Performance Dashboard"
        original = {
            "title": title,
            "datasets": {
                "coffee_sales": [{"coffee_name": "Latte", "revenue": 27866.3}],
                "time_of_day_sales": [{"Time_of_Day": "Night", "revenue": 39033.34}],
            },
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Revenue by Coffee Name",
                            "dataset": "coffee_sales",
                            "x_field": "coffee_name",
                            "y_field": "revenue",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Revenue by Time of Day",
                            "dataset": "time_of_day_sales",
                            "x_field": "Time_of_Day",
                            "y_field": "revenue",
                        },
                    ],
                }
            ],
        }
        noncanonical_revision = {
            "title": title,
            "components": [
                {
                    "type": "pie_chart",
                    "content": {
                        "title": "Revenue by Coffee Name",
                        "dataset_id": "coffee_sales",
                        "label_column": "coffee_name",
                        "value_column": "revenue",
                    },
                },
                {
                    "type": "bar_chart",
                    "content": {
                        "title": "Revenue by Time of Day",
                        "dataset_id": "time_of_day_sales",
                        "x_axis_column": "Time_of_Day",
                        "y_axis_column": "revenue",
                    },
                },
            ],
            "datasets": original["datasets"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.tools["generate_dashboard"](output_dir=tmp, view_model=original)
            revised = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model=noncanonical_revision,
            )

        by_title = {item["title"]: item for item in revised["viewModel"]["sections"][0]["items"]}
        self.assertEqual(by_title["Revenue by Coffee Name"]["chart_type"], "pie")
        self.assertEqual(by_title["Revenue by Time of Day"]["chart_type"], "pie")
        self.assertTrue(revised["revisionMerge"]["auto_revision"])
        self.assertEqual(
            revised["revisionMerge"]["applied_keys"],
            ["revenue by coffee name"],
        )

    def test_dashboard_auto_revision_can_recover_when_latest_memory_record_already_drifted(self):
        title = "Coffee Sales Performance Dashboard"
        original = {
            "title": title,
            "datasets": {
                "coffee_sales": [{"coffee_name": "Latte", "revenue": 27866.3}],
                "time_of_day_sales": [{"Time_of_Day": "Night", "revenue": 39033.34}],
            },
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Revenue by Coffee Name",
                            "dataset": "coffee_sales",
                            "x_field": "coffee_name",
                            "y_field": "revenue",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Revenue by Time of Day",
                            "dataset": "time_of_day_sales",
                            "x_field": "Time_of_Day",
                            "y_field": "revenue",
                        },
                    ],
                }
            ],
        }
        drifted = copy.deepcopy(original)
        drifted["sections"][0]["items"][0]["chart_type"] = "pie"
        drifted["sections"][0]["items"][1]["chart_type"] = "bar"
        with tempfile.TemporaryDirectory() as tmp:
            self.tools["generate_dashboard"](output_dir=tmp, view_model=original)
            self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model=drifted,
                preserve_unspecified=False,
            )
            revised = self.tools["generate_dashboard"](output_dir=tmp, view_model=drifted)

        by_title = {item["title"]: item for item in revised["viewModel"]["sections"][0]["items"]}
        self.assertEqual(by_title["Revenue by Coffee Name"]["chart_type"], "pie")
        self.assertEqual(by_title["Revenue by Time of Day"]["chart_type"], "pie")

    def test_dashboard_revision_note_preserves_unrequested_panel_when_title_changes(self):
        original = {
            "title": "Coffee Sales Performance Dashboard",
            "datasets": {
                "coffee_sales": [{"coffee_name": "Latte", "revenue": 27866.3}],
                "time_of_day_sales": [{"Time_of_Day": "Night", "revenue": 39033.34}],
            },
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Revenue by Coffee Name",
                            "dataset": "coffee_sales",
                            "x_field": "coffee_name",
                            "y_field": "revenue",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Revenue by Time of Day",
                            "dataset": "time_of_day_sales",
                            "x_field": "Time_of_Day",
                            "y_field": "revenue",
                        },
                    ],
                }
            ],
        }
        regenerated = copy.deepcopy(original)
        regenerated["title"] = "Updated Coffee Dashboard"
        regenerated["sections"][0]["items"][0]["chart_type"] = "pie"
        regenerated["sections"][0]["items"][1]["chart_type"] = "bar"
        with tempfile.TemporaryDirectory() as tmp:
            self.tools["generate_dashboard"](output_dir=tmp, view_model=original)
            revised = self.tools["generate_dashboard"](
                output_dir=tmp,
                revision_notes="chart Revenue by Coffee Name diganti pie chart aja",
                view_model=regenerated,
            )

        by_title = {item["title"]: item for item in revised["viewModel"]["sections"][0]["items"]}
        self.assertEqual(by_title["Revenue by Coffee Name"]["chart_type"], "pie")
        self.assertEqual(by_title["Revenue by Time of Day"]["chart_type"], "pie")
        self.assertEqual(
            revised["revisionMerge"]["applied_keys"],
            ["revenue by coffee name"],
        )

    def test_dashboard_revision_prefers_clean_base_over_source_scoped_drifted_memory(self):
        original = {
            "title": "Coffee Sales Dashboard",
            "description": "",
            "datasets": {},
            "kpis": [
                {"label": "Total Sales", "value": 115431.58},
                {"label": "Total Transactions", "value": 3636},
                {"label": "Avg Transaction Value", "value": 31.75},
                {"label": "Top Product", "value": "Latte"},
            ],
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Sales by Coffee Type",
                            "data": [{"x": "Latte", "sales": 27866.3}],
                            "x_field": "x",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "line",
                            "title": "Monthly Sales Trend",
                            "data": [{"x": "Jan", "sales": 6398.86}],
                            "x_field": "x",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Sales by Time of Day",
                            "data": [{"x": "Afternoon", "sales": 39018.04}],
                            "x_field": "x",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Sales by Weekday",
                            "data": [{"x": "Mon", "sales": 17925.1}],
                            "x_field": "x",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Payment Method Distribution",
                            "data": [{"x": "Card", "sales": 112245.58}],
                            "x_field": "x",
                            "y_field": "sales",
                        },
                    ],
                }
            ],
        }
        drifted = {
            "title": "Coffee Sales Dashboard",
            "datasets": {
                "sales_by_coffee": [{"coffee_name": "Latte", "sales": 27866.3}],
                "sales_by_payment": [{"cash_type": "card", "sales": 112245.58}],
                "sales_by_month": [{"Month_name": "Jan", "Monthsort": 1, "sales": 6398.86}],
                "sales_by_weekday": [{"Weekday": "Mon", "Weekdaysort": 1, "sales": 17925.1}],
                "sales_by_time": [{"Time_of_Day": "Night", "sales": 39033.34}],
            },
            "kpis": [
                {"label": "Total Sales", "value": 115431.58, "format": "$,.2f"},
                {"label": "Total Transactions", "value": 3636, "format": ",.0f"},
                {"label": "Avg Transaction Value", "value": 31.74685918591859, "format": "$,.2f"},
            ],
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Sales by Coffee Type",
                            "dataset": "sales_by_coffee",
                            "x_field": "coffee_name",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Sales by Payment Method",
                            "dataset": "sales_by_payment",
                            "x_field": "cash_type",
                            "y_field": "sales",
                        },
                        {
                            "type": "chart",
                            "chart_type": "line",
                            "title": "Monthly Sales Trend",
                            "dataset": "sales_by_month",
                            "x_field": "Month_name",
                            "y_field": "Monthsort",
                        },
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Sales by Weekday",
                            "dataset": "sales_by_weekday",
                            "x_field": "Weekday",
                            "y_field": "Weekdaysort",
                        },
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Sales by Time of Day",
                            "dataset": "sales_by_time",
                            "x_field": "Time_of_Day",
                            "y_field": "sales",
                        },
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(tmp)
            self.tools["generate_dashboard"](output_dir=tmp, view_model=original)
            self.tools["generate_dashboard"](
                output_dir=tmp,
                source_path=path,
                preserve_unspecified=False,
                view_model=drifted,
            )
            revised = self.tools["generate_dashboard"](
                output_dir=tmp,
                source_path=path,
                revision_notes="ubah chart Sales by Coffee Type jadi pie chart",
                view_model=drifted,
            )

        self.assertEqual(len(revised["viewModel"]["kpis"]), 4)
        self.assertEqual(revised["viewModel"]["kpis"][3]["label"], "Top Product")
        items = revised["viewModel"]["sections"][0]["items"]
        self.assertEqual(
            [item["title"] for item in items],
            [
                "Sales by Coffee Type",
                "Monthly Sales Trend",
                "Sales by Time of Day",
                "Sales by Weekday",
                "Payment Method Distribution",
            ],
        )
        by_title = {item["title"]: item for item in items}
        self.assertEqual(by_title["Sales by Coffee Type"]["chart_type"], "pie")
        self.assertEqual(by_title["Sales by Time of Day"]["chart_type"], "pie")
        self.assertEqual(by_title["Monthly Sales Trend"]["y_field"], "sales")
        self.assertEqual(by_title["Sales by Weekday"]["y_field"], "sales")
        self.assertEqual(by_title["Payment Method Distribution"]["chart_type"], "pie")
        self.assertEqual(
            revised["revisionMerge"]["applied_keys"],
            ["sales by coffee type"],
        )

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

    def test_generate_dashboard_hydrates_placeholder_charts_from_cached_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "coffee.csv"
            source.write_text(
                "coffee_name,month,money\nLatte,Jan,10\nLatte,Feb,15\nEspresso,Jan,5\n",
                encoding="utf-8",
            )
            aggregate = self.tools["aggregate_data"](
                path=str(source),
                query=[
                    {
                        "name": "revenue_by_coffee_type",
                        "sql": (
                            "SELECT coffee_name, SUM(money) AS revenue "
                            "FROM data GROUP BY coffee_name ORDER BY revenue DESC"
                        ),
                    },
                    {
                        "name": "monthly_sales",
                        "sql": (
                            "SELECT month, SUM(money) AS sales "
                            "FROM data GROUP BY month ORDER BY month"
                        ),
                    },
                ],
            )
            self.assertEqual(aggregate["errors"], [])

            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Coffee Sales Executive Dashboard",
                    "kpis": [{"label": "Total Revenue", "value": 30}],
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "bar",
                                    "title": "Revenue by Coffee Type",
                                    "data": [],
                                    "x_field": "name",
                                    "y_field": "value",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "line",
                                    "title": "Monthly Sales Trend",
                                    "data": [],
                                    "x_field": "name",
                                    "y_field": "value",
                                },
                            ],
                        }
                    ],
                },
            )
            html_text = Path(result["path"]).read_text(encoding="utf-8")

        items = result["viewModel"]["sections"][0]["items"]
        self.assertEqual(items[0]["dataset"], "revenue_by_coffee_type")
        self.assertEqual(items[0]["x_field"], "coffee_name")
        self.assertEqual(items[0]["y_field"], "revenue")
        self.assertEqual(items[1]["dataset"], "monthly_sales")
        self.assertEqual(items[1]["x_field"], "month")
        self.assertEqual(items[1]["y_field"], "sales")
        self.assertIn("Latte", html_text)
        self.assertIn("Jan", html_text)
        self.assertNotIn("No chart data available.", html_text)

    def test_generate_dashboard_hydrates_placeholder_charts_from_last_source(self):
        import sys

        module = sys.modules["openbench_skill_dashboard_generator"]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "coffee.csv"
            source.write_text(
                "sale_date,coffee_name,Time_of_Day,cash_type,money\n"
                "2026-01-01,Latte,Morning,card,10\n"
                "2026-01-01,Espresso,Night,cash,5\n"
                "2026-01-02,Latte,Night,card,15\n",
                encoding="utf-8",
            )
            metadata = self.tools["extract_metadata"](path=str(source))
            self.assertNotIn("error", metadata)
            module._LAST_AGGREGATE_DATASETS.clear()
            module._LAST_SOURCE_CONTEXT.clear()

            result = self.tools["generate_dashboard"](
                output_dir=tmp,
                view_model={
                    "title": "Coffee Sales Executive Dashboard",
                    "kpis": [{"label": "Total Revenue", "value": 30}],
                    "datasets": {},
                    "sections": [
                        {
                            "title": "Dashboard",
                            "items": [
                                {
                                    "type": "chart",
                                    "chart_type": "line",
                                    "title": "Daily Sales Trend",
                                    "data": [],
                                    "x_field": "name",
                                    "y_field": "value",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "pie",
                                    "title": "Sales by Coffee Type",
                                    "data": [],
                                    "x_field": "name",
                                    "y_field": "value",
                                },
                                {
                                    "type": "chart",
                                    "chart_type": "pie",
                                    "title": "Sales by Payment Method",
                                    "data": [],
                                    "x_field": "name",
                                    "y_field": "value",
                                },
                            ],
                        }
                    ],
                },
            )
            html_text = Path(result["path"]).read_text(encoding="utf-8")

        datasets = result["viewModel"]["datasets"]
        self.assertGreaterEqual(len(datasets), 3)
        by_title = {item["title"]: item for item in result["viewModel"]["sections"][0]["items"]}
        self.assertEqual(by_title["Daily Sales Trend"]["x_field"], "sale_date")
        self.assertEqual(by_title["Sales by Coffee Type"]["x_field"], "coffee_name")
        self.assertEqual(by_title["Sales by Payment Method"]["x_field"], "cash_type")
        self.assertIn("Latte", html_text)
        self.assertIn("card", html_text)
        self.assertIn("2026-01-01", html_text)
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
                    output.write_text(
                        "<html><body>Injected adapter</body></html>", encoding="utf-8"
                    )
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

        self.assertEqual(
            [call["json"]["method"] for call in calls], ["tools/list", "tools/call", "tools/call"]
        )
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

    def test_export_multi_sheet_rejects_empty_list(self):
        result = self.tools["export_multi_sheet_excel"]([], "out.xlsx")
        self.assertIn("error", result)

    def test_export_multi_sheet_rejects_list_entries_without_a_name(self):
        result = self.tools["export_multi_sheet_excel"]([{"records": []}], "out.xlsx")
        self.assertIn("error", result)


class TestFileExportToolDescriptions(unittest.TestCase):
    """The model picks a tool from its description.

    Every export tool must say *when* to use it and cross-reference its
    siblings, or the model settles for an inline markdown table. The
    triggers are named in both languages General Chat is used in.
    """

    SKILLS_AND_TOOLS = {
        "export-excel": ("export_to_excel", "export_multi_sheet_excel"),
        "pdf-tools": ("generate_pdf", "merge_pdfs", "split_pdf"),
        "export-markdown": ("generate_markdown",),
    }

    def _schemas(self, skill_name):
        skill = Skill.from_dir(SDK_SKILLS_DIR / skill_name)
        return {name: schema for name, _, schema in skill.tools}

    def test_export_tools_say_when_to_use_them(self):
        for skill_name, tool_names in self.SKILLS_AND_TOOLS.items():
            schemas = self._schemas(skill_name)
            for tool_name in tool_names:
                with self.subTest(tool=tool_name):
                    description = schemas[tool_name]["function"]["description"].lower()
                    self.assertIn("use", description)
                    self.assertIn("when", description)

    def test_primary_export_tools_name_indonesian_triggers(self):
        for skill_name, tool_name, term in (
            ("export-excel", "export_to_excel", "unduh"),
            ("pdf-tools", "generate_pdf", "unduh"),
            ("export-markdown", "generate_markdown", "simpan sebagai"),
        ):
            with self.subTest(tool=tool_name):
                description = self._schemas(skill_name)[tool_name]["function"][
                    "description"
                ].lower()
                self.assertIn(term, description)

    def test_output_dir_is_not_offered_to_the_model(self):
        # The host resolves the export directory from env; exposing the
        # parameter only invites a bogus path.
        schemas = self._schemas("export-excel")
        for tool_name in ("export_to_excel", "export_multi_sheet_excel"):
            with self.subTest(tool=tool_name):
                params = schemas[tool_name]["function"]["parameters"]["properties"]
                self.assertNotIn("output_dir", params)


class TestFileExportSchemaShapes(unittest.TestCase):
    """Structured parameters of the export tools describe their contents.

    ``sheets`` and ``sections`` used to be bare ``{"type": "object"}``
    with the real shape buried in prose in the description. Free-form
    ``records``/``rows`` lists stay free-form on purpose — the columns
    genuinely are unknown — so this only pins the two structured ones.
    """

    def _properties(self, skill_name, tool_name):
        skill = Skill.from_dir(SDK_SKILLS_DIR / skill_name)
        schema = {name: s for name, _, s in skill.tools}[tool_name]
        return schema["function"]["parameters"]["properties"]

    def test_multi_sheet_sheets_is_a_typed_array(self):
        sheets = self._properties("export-excel", "export_multi_sheet_excel")["sheets"]
        self.assertEqual(sheets["type"], "array")
        item_props = sheets["items"]["properties"]
        self.assertIn("sheet_name", item_props)
        self.assertIn("records", item_props)

    def test_generate_pdf_sections_is_a_typed_array(self):
        sections = self._properties("pdf-tools", "generate_pdf")["sections"]
        self.assertEqual(sections["type"], "array")
        item_props = sections["items"]["properties"]
        self.assertIn("type", item_props)
        self.assertEqual(set(item_props["type"]["enum"]), {"heading", "text", "table"})
        for key in ("content", "headers", "rows"):
            self.assertIn(key, item_props)


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
        self.assertEqual(set(self.tools), {"web_search", "web_search_multi", "fetch_url"})

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

    def _search_source_mock(self, *, answer: str = "jawaban"):
        raw = mock.Mock()
        raw.content = answer
        raw.metadata = {"sources": [{"title": "T", "url": "https://x.example"}]}
        instance = mock.Mock()
        instance.validate.return_value = True
        instance.extract.return_value = raw
        source_cls = mock.Mock(return_value=instance)
        source_cls.ENV_KEYS = {
            "gemini": ["GOOGLE_API_KEY"],
            "perplexity": ["PERPLEXITY_API_KEY"],
        }
        return source_cls, instance

    def test_web_search_falls_back_when_provider_key_missing(self):
        """A provider without a key falls back to a configured one."""
        source_cls, _ = self._search_source_mock()
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            os.environ.pop("PERPLEXITY_API_KEY", None)
            with mock.patch(
                "openbench.data.sources.grounded_search.GroundedSearchSource",
                source_cls,
            ):
                result = self.tools["web_search"]("uji", provider="perplexity")
        self.assertNotIn("error", result)
        self.assertIn("perplexity", result["provider_note"])
        self.assertEqual(source_cls.call_args.kwargs["provider"], "gemini")

    def test_web_search_retries_transient_503(self):
        """A 503/UNAVAILABLE failure is retried and can then succeed."""
        source_cls, instance = self._search_source_mock()
        instance.extract.side_effect = [
            RuntimeError("503 UNAVAILABLE: model is experiencing high demand"),
            instance.extract.return_value,
        ]
        with (
            mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False),
            mock.patch(
                "openbench.data.sources.grounded_search.GroundedSearchSource",
                source_cls,
            ),
            mock.patch("time.sleep") as sleep_mock,
        ):
            result = self.tools["web_search"]("uji")
        self.assertNotIn("error", result)
        self.assertEqual(result["answer"], "jawaban")
        sleep_mock.assert_called()

    def test_web_search_gives_up_after_retries(self):
        source_cls, instance = self._search_source_mock()
        instance.extract.side_effect = RuntimeError("503 UNAVAILABLE")
        with (
            mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False),
            mock.patch(
                "openbench.data.sources.grounded_search.GroundedSearchSource",
                source_cls,
            ),
            mock.patch("time.sleep"),
        ):
            result = self.tools["web_search"]("uji")
        self.assertIn("error", result)
        self.assertIn("after retries", result["error"])

    def test_web_search_does_not_retry_permanent_errors(self):
        source_cls, instance = self._search_source_mock()
        instance.validate.side_effect = ValueError("API key required for gemini")
        with (
            mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=False),
            mock.patch(
                "openbench.data.sources.grounded_search.GroundedSearchSource",
                source_cls,
            ),
            mock.patch("time.sleep") as sleep_mock,
        ):
            result = self.tools["web_search"]("uji")
        self.assertIn("error", result)
        sleep_mock.assert_not_called()


class TestWebSearchFetchUrl(unittest.TestCase):
    """Tests for the fetch_url tool on the web-search SDK skill."""

    _PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "web-search")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.fetch_url = self.tools["fetch_url"]

    def _mock_response(
        self,
        *,
        body: bytes = b"<html><head><title>T</title></head>"
        b"<body><script>secret()</script><p>Hello world</p></body></html>",
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com/page",
        status_code: int = 200,
    ):
        response = mock.Mock()
        response.url = url
        response.status_code = status_code
        response.headers = {"content-type": content_type}
        response.encoding = "utf-8"
        response.iter_content = lambda chunk_size: iter([body])
        response.raise_for_status = mock.Mock()
        response.close = mock.Mock()
        return response

    def test_schema_shape(self):
        schema = next(s for n, _, s in self.skill.tools if n == "fetch_url")
        self.assertEqual(schema["function"]["name"], "fetch_url")
        self.assertEqual(schema["function"]["parameters"]["required"], ["url"])

    def test_empty_url_returns_error(self):
        self.assertIn("error", self.fetch_url(""))
        self.assertIn("error", self.fetch_url("   "))

    def test_rejects_non_http_schemes(self):
        for url in ("ftp://example.com/file", "file:///etc/passwd", "not-a-url"):
            self.assertIn("error", self.fetch_url(url), url)

    def test_rejects_localhost_and_private_addresses(self):
        for url in (
            "http://localhost:8005/health",
            "http://127.0.0.1/",
            "http://192.168.1.10/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/",
        ):
            result = self.fetch_url(url)
            self.assertIn("error", result, url)
            self.assertIn("private or local", result["error"], url)

    def test_happy_path_html(self):
        with (
            mock.patch("socket.getaddrinfo", return_value=self._PUBLIC_ADDRINFO),
            mock.patch("requests.get", return_value=self._mock_response()),
        ):
            result = self.fetch_url("https://example.com/page")
        self.assertNotIn("error", result)
        self.assertEqual(result["title"], "T")
        self.assertIn("Hello world", result["text"])
        self.assertNotIn("secret", result["text"])
        self.assertEqual(result["content_type"], "text/html")
        self.assertFalse(result["truncated"])

    def test_max_chars_truncates(self):
        body = b"<html><body><p>" + b"word " * 2000 + b"</p></body></html>"
        with (
            mock.patch("socket.getaddrinfo", return_value=self._PUBLIC_ADDRINFO),
            mock.patch("requests.get", return_value=self._mock_response(body=body)),
        ):
            result = self.fetch_url("https://example.com/page", max_chars=10)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["text"]), 10)

    def test_network_failure_returns_error(self):
        with (
            mock.patch("socket.getaddrinfo", return_value=self._PUBLIC_ADDRINFO),
            mock.patch("requests.get", side_effect=Exception("boom")),
        ):
            result = self.fetch_url("https://example.com/page")
        self.assertIn("error", result)
        self.assertIn("boom", result["error"])

    def test_binary_content_type_returns_error(self):
        response = self._mock_response(content_type="application/pdf", body=b"%PDF-")
        with (
            mock.patch("socket.getaddrinfo", return_value=self._PUBLIC_ADDRINFO),
            mock.patch("requests.get", return_value=response),
        ):
            result = self.fetch_url("https://example.com/report.pdf")
        self.assertIn("error", result)
        self.assertIn("chat source", result["error"])

    def test_raw_text_content_returned_verbatim(self):
        response = self._mock_response(content_type="application/json", body=b'{"ok": true}')
        with (
            mock.patch("socket.getaddrinfo", return_value=self._PUBLIC_ADDRINFO),
            mock.patch("requests.get", return_value=response),
        ):
            result = self.fetch_url("https://api.example.com/data")
        self.assertEqual(result["text"], '{"ok": true}')

    def test_redirect_to_private_address_rejected(self):
        # The final URL after redirects points at loopback: the guard on
        # response.url must reject even though the original host is public.
        def fake_getaddrinfo(host, *args, **kwargs):
            if host == "example.com":
                return self._PUBLIC_ADDRINFO
            return [(2, 1, 6, "", ("127.0.0.1", 0))]

        response = self._mock_response(url="http://127.0.0.1/admin")
        with (
            mock.patch("socket.getaddrinfo", side_effect=fake_getaddrinfo),
            mock.patch("requests.get", return_value=response),
        ):
            result = self.fetch_url("https://example.com/page")
        self.assertIn("error", result)
        self.assertIn("private or local", result["error"])


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


# ---------------------------------------------------------------------------
# source-retrieval
# ---------------------------------------------------------------------------


class _FakeScope:
    """Stand-in for the host's per-turn source scope."""

    def __init__(self, source_ids, owner="alice@example.com", session_id="s1"):
        self.source_ids = tuple(source_ids)
        self.owner = owner
        self.session_id = session_id


class _FakeSearchResult:
    def __init__(self, items, scores):
        self.items = items
        self.scores = scores
        self.total = len(items)


class _FakeIndex:
    """Minimal DocumentIndexStore stand-in recording what it was asked."""

    def __init__(self):
        self.last_query = None
        self.raise_on_search = False

    def search(self, query):
        self.last_query = query
        if self.raise_on_search:
            raise RuntimeError("index offline")
        return _FakeSearchResult(
            items=[
                {
                    "id": "source-a-chunk-2",
                    "content": "Revenue rose twelve percent.",
                    "metadata": {
                        "source_id": "source-a",
                        "name": "laporan.pdf",
                        "chunk_index": 2,
                        "total_chunks": 9,
                        "heading": "Pendapatan",
                    },
                }
            ],
            scores=[0.87],
        )

    def read_range(self, source_id, start_index=0, chunk_count=4):
        return [
            {
                "id": f"{source_id}-chunk-{index}",
                "content": f"Body of chunk {index}.",
                "metadata": {
                    "source_id": source_id,
                    "name": "laporan.pdf",
                    "chunk_index": index,
                    "total_chunks": 9,
                },
            }
            for index in range(start_index, min(start_index + chunk_count, 9))
        ]

    def outline(self, source_id):
        return [{"heading": "Pendapatan", "chunk_index": 2, "page": None}]


class SourceRetrievalTestCase(unittest.TestCase):
    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "source-retrieval")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.module = sys.modules["openbench_skill_source_retrieval"]
        self.index = _FakeIndex()
        self.module.bind(
            source_index=self.index,
            source_scope_provider=lambda: _FakeScope(["source-a", "source-b"]),
        )

    def tearDown(self):
        self.module.bind(source_index=None, source_scope_provider=None)


class TestSourceRetrievalSkill(SourceRetrievalTestCase):
    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools), {"search_sources", "read_source_section", "outline_source"}
        )

    def test_search_returns_flattened_hits(self):
        result = self.tools["search_sources"]("revenue")
        self.assertEqual(result["count"], 1)
        hit = result["results"][0]
        self.assertEqual(hit["source_id"], "source-a")
        self.assertEqual(hit["source_name"], "laporan.pdf")
        self.assertEqual(hit["chunk_index"], 2)
        self.assertEqual(hit["heading"], "Pendapatan")
        self.assertIn("content", hit)

    def test_search_scopes_to_the_turn_by_default(self):
        self.tools["search_sources"]("revenue")
        self.assertEqual(self.index.last_query.filters["source_ids"], ["source-a", "source-b"])

    def test_search_filters_carry_no_owner(self):
        # Scoped ids span owners (session sources + admin globals); an
        # owner filter would silently drop the other owner's sources.
        self.tools["search_sources"]("revenue")
        self.assertNotIn("owner", self.index.last_query.filters)

    def test_search_honours_explicit_source_ids(self):
        self.tools["search_sources"]("revenue", source_ids=["source-b"])
        self.assertEqual(self.index.last_query.filters["source_ids"], ["source-b"])

    def test_search_rejects_out_of_scope_source_id(self):
        result = self.tools["search_sources"]("revenue", source_ids=["source-someone-else"])
        self.assertIn("error", result)
        self.assertIn("source-someone-else", result["error"])
        self.assertIsNone(self.index.last_query)

    def test_top_k_is_capped(self):
        self.tools["search_sources"]("revenue", top_k=9999)
        self.assertLessEqual(self.index.last_query.limit, 12)

    def test_empty_query_is_an_error(self):
        self.assertIn("error", self.tools["search_sources"]("   "))

    def test_index_failure_is_reported_not_raised(self):
        self.index.raise_on_search = True
        result = self.tools["search_sources"]("revenue")
        self.assertIn("error", result)

    def test_read_section_returns_ordered_sections(self):
        result = self.tools["read_source_section"]("source-a", start_chunk=1, chunk_count=3)
        self.assertEqual(result["count"], 3)
        indexes = [section["chunk_index"] for section in result["sections"]]
        self.assertEqual(indexes, [1, 2, 3])

    def test_read_section_rejects_out_of_scope_source(self):
        self.assertIn("error", self.tools["read_source_section"]("source-other"))

    def test_read_section_past_end_reports_a_note(self):
        result = self.tools["read_source_section"]("source-a", start_chunk=500)
        self.assertEqual(result["count"], 0)
        self.assertIn("note", result)

    def test_outline_returns_headings(self):
        result = self.tools["outline_source"]("source-a")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["outline"][0]["heading"], "Pendapatan")

    def test_outline_rejects_out_of_scope_source(self):
        self.assertIn("error", self.tools["outline_source"]("source-other"))


class TestSourceRetrievalUnbound(unittest.TestCase):
    """Without a bound index every tool must degrade, not raise."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "source-retrieval")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.module = sys.modules["openbench_skill_source_retrieval"]
        self.module.bind(source_index=None, source_scope_provider=None)

    def test_all_tools_return_an_error(self):
        self.assertIn("error", self.tools["search_sources"]("anything"))
        self.assertIn("error", self.tools["read_source_section"]("source-a"))
        self.assertIn("error", self.tools["outline_source"]("source-a"))


# ---------------------------------------------------------------------------
# table-query
# ---------------------------------------------------------------------------


class _FakeColumn:
    def __init__(self, name, dtype="int64"):
        self.name = name
        self.dtype = dtype
        self.null_count = 0
        self.distinct_estimate = None
        self.min = None
        self.max = None
        self.sample_values = []


class _FakeArtifact:
    def __init__(self, source_id, name, parquet_path, columns):
        self.source_id = source_id
        self.name = name
        self.display_name = name.title()
        self.parquet_path = parquet_path
        self.row_count = 4
        self.columns = [_FakeColumn(column) for column in columns]
        self.sample_rows = [{columns[0]: 1}]


class _FakeCatalog:
    def __init__(self, artifacts):
        self._artifacts = artifacts

    def list_for(self, *, source_ids=None, session_id=None, owner=None):
        if source_ids is None:
            return list(self._artifacts)
        return [a for a in self._artifacts if a.source_id in set(source_ids)]

    def get_by_name(self, name):
        return next((a for a in self._artifacts if a.name == name), None)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("duckdb") is not None
    and __import__("importlib").util.find_spec("pandas") is not None,
    "duckdb and pandas are not installed",
)
class TableQueryTestCase(unittest.TestCase):
    def setUp(self):
        import pandas as pd

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        parquet = root / "sales.parquet"
        pd.DataFrame(
            {"region": ["North", "South", "North", "East"], "amount": [100, 250, 50, 75]}
        ).to_parquet(parquet)

        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "table-query")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.module = sys.modules["openbench_skill_table_query"]
        self.catalog = _FakeCatalog(
            [_FakeArtifact("source-a", "sales", str(parquet), ["region", "amount"])]
        )
        self.module.bind(
            table_catalog=self.catalog,
            source_scope_provider=lambda: _FakeScope(["source-a"]),
        )

    def tearDown(self):
        self.module.bind(table_catalog=None, source_scope_provider=None)
        self._tmp.cleanup()


class TestTableQuerySkill(TableQueryTestCase):
    def test_expected_tools_present(self):
        self.assertEqual(
            set(self.tools),
            {"list_source_tables", "describe_source_table", "query_source_table"},
        )

    def test_list_tables(self):
        result = self.tools["list_source_tables"]()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tables"][0]["table"], "sales")

    def test_describe_table(self):
        result = self.tools["describe_source_table"]("sales")
        self.assertEqual([c["name"] for c in result["columns"]], ["region", "amount"])

    def test_describe_unknown_table_lists_alternatives(self):
        result = self.tools["describe_source_table"]("nope")
        self.assertIn("error", result)
        self.assertEqual(result["available_tables"], ["sales"])

    def test_query_returns_correct_aggregate(self):
        result = self.tools["query_source_table"](
            "SELECT region, SUM(amount) AS total FROM sales GROUP BY region"
        )
        totals = {row[0]: row[1] for row in result["rows"]}
        self.assertEqual(totals["North"], 150)
        self.assertEqual(totals["South"], 250)

    def test_query_rejects_writes_with_a_hint(self):
        result = self.tools["query_source_table"]("DROP TABLE sales")
        self.assertIn("error", result)
        self.assertIn("available_columns", result)
        self.assertIn("hint", result)

    def test_query_rejects_file_access(self):
        result = self.tools["query_source_table"]("SELECT * FROM read_parquet('/etc/passwd')")
        self.assertIn("error", result)

    def test_bad_column_returns_available_columns(self):
        result = self.tools["query_source_table"]("SELECT nope FROM sales")
        self.assertIn("error", result)
        self.assertEqual(result["available_columns"]["sales"], ["region", "amount"])

    def test_unknown_table_argument_is_rejected(self):
        result = self.tools["query_source_table"]("SELECT 1", tables=["ghost"])
        self.assertIn("error", result)
        self.assertEqual(result["available_tables"], ["sales"])

    def test_empty_sql_is_an_error(self):
        self.assertIn("error", self.tools["query_source_table"]("  "))

    def test_query_tool_declares_a_timeout(self):
        self.assertTrue(hasattr(self.tools["query_source_table"], "timeout_seconds"))


class TestTableQueryScopeIsolation(TableQueryTestCase):
    def test_out_of_scope_source_exposes_no_tables(self):
        self.module.bind(
            table_catalog=self.catalog,
            source_scope_provider=lambda: _FakeScope(["source-someone-else"]),
        )
        self.assertEqual(self.tools["list_source_tables"]()["count"], 0)
        self.assertIn("error", self.tools["query_source_table"]("SELECT 1"))

    def test_empty_scope_exposes_no_tables(self):
        self.module.bind(table_catalog=self.catalog, source_scope_provider=lambda: _FakeScope([]))
        self.assertEqual(self.tools["list_source_tables"]()["count"], 0)


class TestTableQueryUnbound(unittest.TestCase):
    """Without a bound catalog every tool must degrade, not raise."""

    def setUp(self):
        self.skill = Skill.from_dir(SDK_SKILLS_DIR / "table-query")
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        sys.modules["openbench_skill_table_query"].bind(
            table_catalog=None, source_scope_provider=None
        )

    def test_all_tools_return_an_error(self):
        self.assertIn("error", self.tools["list_source_tables"]())
        self.assertIn("error", self.tools["describe_source_table"]("sales"))
        self.assertIn("error", self.tools["query_source_table"]("SELECT 1"))


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
        # data-context-extractor(2) + dashboard-generator(4)
        # + data-visualization(5) + export-excel(2) + export-markdown(1)
        # + pdf-tools(7) + query-explorer(5) + web-search(8)
        # + memory-scratchpad(4) + source-retrieval(3) + table-query(3)
        # = 44 tools
        self.assertEqual(len(tools), 44)

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
