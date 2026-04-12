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
