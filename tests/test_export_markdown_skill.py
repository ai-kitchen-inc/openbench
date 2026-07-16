"""Tests for the export-markdown SDK skill."""

from __future__ import annotations

import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from openbench.intelligence.skill import Skill

SKILL_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "openbench" / "skills" / "export-markdown"
)


class TestExportMarkdownSkill(unittest.TestCase):
    def _tool(self):
        skill = Skill.from_dir(SKILL_DIR)
        tools = {name: fn for name, fn, _schema in skill.tools}
        return skill, tools["generate_markdown"]

    def test_skill_discovers_single_tool_with_schema(self):
        skill, _fn = self._tool()
        self.assertEqual(skill.name, "export-markdown")
        names = [name for name, _fn, _schema in skill.tools]
        self.assertEqual(names, ["generate_markdown"])
        _, _, schema = skill.tools[0]
        self.assertEqual(schema["function"]["name"], "generate_markdown")
        self.assertEqual(
            schema["function"]["parameters"]["required"], ["content", "filename"]
        )

    def test_generate_markdown_writes_file_and_returns_render_item(self):
        _skill, generate_markdown = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                environ,
                {
                    "OPENBENCH_EXPORT_DIR": tmp,
                    "OPENBENCH_EXPORT_URL_BASE": "/downloads",
                },
                clear=False,
            ):
                item = generate_markdown("Hello **world**", "notes.md", title="Notes")
            self.assertNotIn("error", item)
            self.assertTrue(item["name"].startswith("notes-"))
            self.assertTrue(item["name"].endswith(".md"))
            self.assertEqual(item["mimeType"], "text/markdown")
            self.assertTrue(item["url"].startswith("/downloads/"))
            written = (Path(tmp) / item["name"]).read_text(encoding="utf-8")
            self.assertTrue(written.startswith("# Notes\n\nHello **world**"))

    def test_unique_suffix_prevents_clobbering(self):
        _skill, generate_markdown = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(environ, {"OPENBENCH_EXPORT_DIR": tmp}, clear=False):
                first = generate_markdown("one", "report")
                second = generate_markdown("two", "report")
            self.assertNotEqual(first["name"], second["name"])

    def test_empty_content_is_error(self):
        _skill, generate_markdown = self._tool()
        self.assertIn("error", generate_markdown("   ", "x.md"))


if __name__ == "__main__":
    unittest.main()
