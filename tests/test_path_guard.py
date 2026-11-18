"""Tests for openbench.utils.path_guard and the tools that use it."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openbench.intelligence.skill import Skill
from openbench.utils import path_guard
from openbench.utils.path_guard import (
    TOOL_FILE_ROOTS_ENV,
    ToolPathError,
    is_within_roots,
    resolve_tool_path,
    tool_file_roots,
)

SDK_SKILLS_DIR = Path(__file__).resolve().parents[1] / "src" / "openbench" / "skills"


class _TreeMixin:
    def _tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)  # type: ignore[attr-defined]
        base = Path(tmp.name).resolve()
        (base / "allowed" / "sub").mkdir(parents=True)
        (base / "allowed" / "sub" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (base / "allowed2").mkdir()
        (base / "outside").mkdir()
        (base / "outside" / "secret.csv").write_text("k,v\nsecret,1\n", encoding="utf-8")
        return base

    def _jail(self, *roots: Path):
        value = os.pathsep.join(str(root) for root in roots)
        patcher = mock.patch.dict(os.environ, {TOOL_FILE_ROOTS_ENV: value})
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]


class TestPathGuard(_TreeMixin, unittest.TestCase):
    def test_unset_means_unrestricted_and_path_is_untouched(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(TOOL_FILE_ROOTS_ENV, None)
            self.assertEqual(tool_file_roots(), [])
            self.assertEqual(resolve_tool_path("relative/file.csv"), Path("relative/file.csv"))
            self.assertEqual(resolve_tool_path("/etc/passwd"), Path("/etc/passwd"))

    def test_empty_value_means_unrestricted(self):
        with mock.patch.dict(os.environ, {TOOL_FILE_ROOTS_ENV: "  "}):
            self.assertEqual(tool_file_roots(), [])
            self.assertEqual(resolve_tool_path("/etc/passwd"), Path("/etc/passwd"))

    def test_roots_are_parsed_and_resolved(self):
        base = self._tree()
        self._jail(base / "allowed", base / "allowed2")
        self.assertEqual(tool_file_roots(), [base / "allowed", base / "allowed2"])

    def test_path_inside_a_root_is_resolved(self):
        base = self._tree()
        self._jail(base / "allowed")
        target = base / "allowed" / "sub" / "data.csv"
        self.assertEqual(resolve_tool_path(str(target)), target)
        # A not-yet-existing file inside the root is fine (tools create outputs).
        self.assertEqual(
            resolve_tool_path(str(base / "allowed" / "new.html")), base / "allowed" / "new.html"
        )

    def test_paths_outside_every_root_are_refused(self):
        base = self._tree()
        self._jail(base / "allowed")
        for candidate in (
            base / "outside" / "secret.csv",
            base / "allowed" / ".." / "outside" / "secret.csv",
            base / "allowed" / "sub" / ".." / ".." / "outside" / "secret.csv",
            Path("/proc/1/environ"),
            Path("/etc/passwd"),
            # A sibling that shares the root's name as a prefix.
            base / "allowed2" / "x.csv",
        ):
            with self.assertRaises(ToolPathError, msg=str(candidate)):
                resolve_tool_path(str(candidate))

    def test_tool_path_error_is_a_value_error(self):
        self.assertTrue(issubclass(ToolPathError, ValueError))

    def test_symlink_escape_is_refused(self):
        base = self._tree()
        link = base / "allowed" / "link.csv"
        try:
            link.symlink_to(base / "outside" / "secret.csv")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available on this platform/user")
        self._jail(base / "allowed")
        with self.assertRaises(ToolPathError):
            resolve_tool_path(str(link))

    def test_explicit_roots_override_the_environment(self):
        base = self._tree()
        self._jail(base / "allowed")
        outside = base / "outside" / "secret.csv"
        self.assertEqual(resolve_tool_path(str(outside), roots=[base / "outside"]), outside)
        self.assertEqual(resolve_tool_path(str(outside), roots=[]), Path(str(outside)))

    def test_is_within_roots(self):
        base = self._tree()
        self.assertTrue(is_within_roots(base / "allowed" / "sub", [base / "allowed"]))
        self.assertFalse(is_within_roots(base / "outside", [base / "allowed"]))
        self.assertFalse(is_within_roots(base / "allowed", []))


class TestSkillsHonorTheJail(_TreeMixin, unittest.TestCase):
    """SDK tools report a jailed path exactly like a missing file."""

    def _tools(self, skill_name: str) -> dict:
        skill = Skill.from_dir(SDK_SKILLS_DIR / skill_name)
        return {name: fn for name, fn, _ in skill.tools}

    def test_data_context_extractor(self):
        base = self._tree()
        tools = self._tools("data-context-extractor")
        inside = str(base / "allowed" / "sub" / "data.csv")
        outside = str(base / "outside" / "secret.csv")

        # No jail: both readable (library behavior is unchanged).
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(TOOL_FILE_ROOTS_ENV, None)
            self.assertNotIn("error", tools["extract_file_context"](outside))

        self._jail(base / "allowed")
        self.assertNotIn("error", tools["extract_file_context"](inside))
        for tool in ("extract_file_context", "read_csv_file", "get_column_profile"):
            result = tools[tool](outside)
            self.assertIn("error", result, tool)
            self.assertIn("File not found", result["error"], tool)
            self.assertNotIn("secret", str(result.get("sample", "")), tool)

    def test_pdf_tools(self):
        base = self._tree()
        (base / "outside" / "doc.pdf").write_bytes(b"%PDF-1.4\n")
        tools = self._tools("pdf-tools")
        self._jail(base / "allowed")
        outside = str(base / "outside" / "doc.pdf")
        for tool in ("pdf_metadata", "read_pdf"):
            result = tools[tool](outside)
            self.assertIn("error", result, tool)
            self.assertIn("File not found", result["error"], tool)
        merged = tools["merge_pdfs"]([outside, outside])
        self.assertIn("File not found", merged["error"])

    def test_dashboard_generator_template_and_output_dir(self):
        import importlib.util

        base = self._tree()
        spec = importlib.util.spec_from_file_location(
            "ob_dashboard_tools_under_test", SDK_SKILLS_DIR / "dashboard-generator" / "tools.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        template = base / "outside" / "template.html"
        template.write_text("<h1>{{title}}</h1>", encoding="utf-8")
        export_dir = base / "allowed"
        with mock.patch.dict(os.environ, {"OPENBENCH_EXPORT_DIR": str(export_dir)}):
            self._jail(base / "allowed")
            options = module._dashboard_template_options(template_path=str(template))
            self.assertNotIn("template_text", options or {})
            # An output_dir outside the jail falls back to the export dir.
            self.assertEqual(module._safe_output_dir(str(base / "outside")), export_dir)
            self.assertEqual(module._safe_output_dir(None), export_dir)
            self.assertEqual(
                module._safe_output_dir(str(base / "allowed" / "sub")), base / "allowed" / "sub"
            )

    def test_dashboard_generator_refuses_template_outside_the_jail(self):
        from openbench.output.generators.dashboard.generator import DashboardGenerator

        base = self._tree()
        template = base / "outside" / "template.html"
        template.write_text("<h1>x</h1>", encoding="utf-8")
        self._jail(base / "allowed")
        generator = DashboardGenerator.__new__(DashboardGenerator)
        with self.assertRaises(ToolPathError):
            generator._resolve_template_source({"template_path": str(template)})


class TestModuleSurface(unittest.TestCase):
    def test_env_name(self):
        self.assertEqual(path_guard.TOOL_FILE_ROOTS_ENV, "OPENBENCH_TOOL_FILE_ROOTS")


if __name__ == "__main__":
    unittest.main()
