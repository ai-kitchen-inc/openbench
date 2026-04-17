"""Tests for ScratchpadStore, LocalMarkdownScratchpad, and memory-scratchpad skill."""

import os
import tempfile
import unittest
from pathlib import Path

from openbench.intelligence.scratchpad import ScratchpadStore
from openbench.intelligence.scratchpads.local_md import (
    LocalMarkdownScratchpad,
    _validate_key,
)


class TestScratchpadStoreABC(unittest.TestCase):
    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            ScratchpadStore()  # type: ignore[abstract]


class TestKeyValidation(unittest.TestCase):
    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            _validate_key("")

    def test_dotdot_rejected(self):
        with self.assertRaises(ValueError):
            _validate_key("../secrets")

    def test_leading_slash_rejected(self):
        with self.assertRaises(ValueError):
            _validate_key("/etc/passwd")

    def test_windows_backslash_traversal_rejected(self):
        with self.assertRaises(ValueError):
            _validate_key("foo\\..\\bar")

    def test_nul_byte_rejected(self):
        with self.assertRaises(ValueError):
            _validate_key("foo\x00bar")

    def test_dot_segment_rejected(self):
        with self.assertRaises(ValueError):
            _validate_key("./foo")

    def test_valid_bare_key_accepted(self):
        self.assertEqual(_validate_key("default"), "default")

    def test_valid_hierarchical_key_accepted(self):
        self.assertEqual(_validate_key("projects/lci-q1"), "projects/lci-q1")


class TestLocalMarkdownScratchpad(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.pad = LocalMarkdownScratchpad(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_read_absent_key_returns_empty_string(self):
        self.assertEqual(self.pad.read("missing"), "")

    def test_write_then_read_roundtrip(self):
        self.pad.write("default", "hello world")
        self.assertEqual(self.pad.read("default"), "hello world")

    def test_write_overwrites(self):
        self.pad.write("k", "v1")
        self.pad.write("k", "v2")
        self.assertEqual(self.pad.read("k"), "v2")

    def test_write_hierarchical_creates_subdir(self):
        self.pad.write("projects/q1", "notes")
        self.assertEqual(self.pad.read("projects/q1"), "notes")
        self.assertTrue((Path(self._tmpdir.name) / "projects" / "q1.md").exists())

    def test_append_creates_key(self):
        self.pad.append("fresh", "first block")
        self.assertEqual(self.pad.read("fresh"), "first block")

    def test_append_adds_newline_separator(self):
        self.pad.write("log", "first")
        self.pad.append("log", "second")
        self.assertEqual(self.pad.read("log"), "first\nsecond")

    def test_append_preserves_trailing_newline(self):
        self.pad.write("log", "first\n")
        self.pad.append("log", "second")
        self.assertEqual(self.pad.read("log"), "first\nsecond")

    def test_append_to_empty_file_behaves_like_write(self):
        self.pad.write("empty", "")
        self.pad.append("empty", "content")
        self.assertEqual(self.pad.read("empty"), "content")

    def test_list_keys_returns_sorted(self):
        self.pad.write("b", "")
        self.pad.write("a", "")
        self.pad.write("projects/c", "")
        self.assertEqual(self.pad.list_keys(), ["a", "b", "projects/c"])

    def test_list_keys_ignores_non_md_files(self):
        (Path(self._tmpdir.name) / "ignore.txt").write_text("not markdown")
        self.pad.write("keep", "yes")
        self.assertEqual(self.pad.list_keys(), ["keep"])

    def test_delete_removes_file(self):
        self.pad.write("k", "v")
        self.pad.delete("k")
        self.assertEqual(self.pad.read("k"), "")

    def test_delete_absent_key_is_noop(self):
        self.pad.delete("never-existed")

    def test_rejects_key_with_parent_traversal(self):
        with self.assertRaises(ValueError):
            self.pad.read("../passwd")

    def test_rejects_symlink_on_read(self):
        real = Path(self._tmpdir.name) / "real.md"
        real.write_text("real content")
        link = Path(self._tmpdir.name) / "link.md"
        os.symlink(real, link)
        with self.assertRaises(ValueError):
            self.pad.read("link")

    def test_tilde_expansion(self):
        # Using HOME shim so we don't touch the real home dir
        with tempfile.TemporaryDirectory() as fake_home:
            saved = os.environ.get("HOME")
            os.environ["HOME"] = fake_home
            try:
                pad = LocalMarkdownScratchpad("~/scratch")
                pad.write("k", "v")
                self.assertTrue(Path(fake_home).joinpath("scratch", "k.md").exists())
            finally:
                if saved is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = saved


class TestMemoryScratchpadSkill(unittest.TestCase):
    """End-to-end tests for the bundled memory-scratchpad skill.

    Load the skill, bind it to an in-memory scratchpad, call each
    tool, and verify the tool operates on the bound store.
    """

    def setUp(self):
        from openbench.intelligence.skill import Skill

        self._tmpdir = tempfile.TemporaryDirectory()
        self.pad = LocalMarkdownScratchpad(self._tmpdir.name)

        skill_dir = Path(__file__).resolve().parent.parent / (
            "src/openbench/skills/memory-scratchpad"
        )
        self.skill = Skill.from_dir(skill_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_skill_has_four_tools(self):
        tool_names = [name for name, _, _ in self.skill.tools]
        self.assertCountEqual(
            tool_names,
            ["read_memory", "write_memory", "append_memory", "list_memory_keys"],
        )

    def test_tools_require_bind_before_use(self):
        read_fn = {n: f for n, f, _ in self.skill.tools}["read_memory"]
        with self.assertRaises(RuntimeError):
            read_fn("default")

    def test_bind_enables_tool_execution(self):
        self.assertTrue(self.skill.bind(scratchpad=self.pad))
        tools = {n: f for n, f, _ in self.skill.tools}

        tools["write_memory"]("default", "hello")
        self.assertEqual(tools["read_memory"]("default"), "hello")

        tools["append_memory"]("default", "world")
        self.assertEqual(tools["read_memory"]("default"), "hello\nworld")

        self.assertEqual(tools["list_memory_keys"](), ["default"])

    def test_bind_ignores_extra_kwargs(self):
        # bind() signature uses **_ to be forward-compatible with new
        # injected kwargs — it should not error on surprise keys.
        self.skill.bind(scratchpad=self.pad, something_else="ok")


if __name__ == "__main__":
    unittest.main()
