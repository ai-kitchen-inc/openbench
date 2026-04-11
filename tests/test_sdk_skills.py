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

from openbench.intelligence.skill import Skill
from openbench.intelligence.skill_registry import SkillRegistry

SDK_SKILLS_DIR = Path(__file__).resolve().parent.parent / "src" / "openbench" / "skills"


class TestSDKSkillsDiscovery(unittest.TestCase):
    """All 4 RFC-required SDK skills must exist and be discoverable."""

    REQUIRED_SKILLS = {
        "data-context-extractor",
        "data-visualization",
        "export-excel",
        "query-explorer",
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
        # 4 + 5 + 2 + 5 = 16 tools
        self.assertEqual(len(tools), 16)

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
        self.assertGreaterEqual(len(summary["sdk_skills"]), 4)
        self.assertGreater(summary["total_tools"], 0)


if __name__ == "__main__":
    unittest.main()
