"""Tests for PersonaSource ABC, FilesystemPersonaSource, InlinePersonaSource,
Persona.from_source, BaseAgent(persona=PersonaSource), and the LocalStorageBackend
persona_source() wiring.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from openbench.intelligence.persona import Persona
from openbench.intelligence.persona_source import (
    FilesystemPersonaSource,
    InlinePersonaSource,
    PersonaSource,
)


class TestPersonaSourceABC(unittest.TestCase):
    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            PersonaSource()  # type: ignore[abstract]

    def test_keys_are_canonical(self):
        self.assertEqual(PersonaSource.KEYS, ("soul", "style", "agents"))


class TestInlinePersonaSource(unittest.TestCase):
    def test_fetch_known_key(self):
        source = InlinePersonaSource(soul="SOUL", style="STYLE", agents="AGENTS")
        self.assertEqual(source.fetch("soul"), "SOUL")
        self.assertEqual(source.fetch("style"), "STYLE")
        self.assertEqual(source.fetch("agents"), "AGENTS")

    def test_fetch_unknown_key_returns_empty(self):
        source = InlinePersonaSource()
        self.assertEqual(source.fetch("unknown"), "")

    def test_defaults_are_empty(self):
        source = InlinePersonaSource()
        for key in ("soul", "style", "agents"):
            self.assertEqual(source.fetch(key), "")

    def test_repr_lists_filled_keys(self):
        source = InlinePersonaSource(soul="I am.")
        self.assertIn("soul", repr(source))

    def test_available_keys_defaults_to_all(self):
        self.assertEqual(
            InlinePersonaSource().available_keys(),
            ["soul", "style", "agents"],
        )


class TestFilesystemPersonaSource(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name: str, content: str) -> None:
        (self.dir / name).write_text(content, encoding="utf-8")

    def test_missing_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            FilesystemPersonaSource(self.dir / "does-not-exist")

    def test_fetch_reads_soul(self):
        self._write("SOUL.md", "You are the soul.")
        source = FilesystemPersonaSource(self.dir)
        self.assertEqual(source.fetch("soul"), "You are the soul.")

    def test_fetch_reads_all_three(self):
        self._write("SOUL.md", "A")
        self._write("STYLE.md", "B")
        self._write("AGENTS.md", "C")
        source = FilesystemPersonaSource(self.dir)
        self.assertEqual(source.fetch("soul"), "A")
        self.assertEqual(source.fetch("style"), "B")
        self.assertEqual(source.fetch("agents"), "C")

    def test_missing_file_returns_empty(self):
        source = FilesystemPersonaSource(self.dir)
        self.assertEqual(source.fetch("soul"), "")

    def test_unknown_key_returns_empty(self):
        self._write("SOUL.md", "A")
        source = FilesystemPersonaSource(self.dir)
        self.assertEqual(source.fetch("unknown"), "")

    def test_strips_trailing_whitespace(self):
        self._write("SOUL.md", "content\n\n")
        source = FilesystemPersonaSource(self.dir)
        self.assertEqual(source.fetch("soul"), "content")

    def test_symlink_rejected(self):
        real = self.dir / "real_soul.md"
        real.write_text("content", encoding="utf-8")
        link = self.dir / "SOUL.md"
        os.symlink(real, link)
        source = FilesystemPersonaSource(self.dir)
        with self.assertRaises(ValueError):
            source.fetch("soul")

    def test_tilde_expansion(self):
        with tempfile.TemporaryDirectory() as fake_home:
            saved = os.environ.get("HOME")
            os.environ["HOME"] = fake_home
            try:
                persona_dir = Path(fake_home) / "p"
                persona_dir.mkdir()
                (persona_dir / "SOUL.md").write_text("X", encoding="utf-8")
                source = FilesystemPersonaSource("~/p")
                self.assertEqual(source.fetch("soul"), "X")
            finally:
                if saved is None:
                    del os.environ["HOME"]
                else:
                    os.environ["HOME"] = saved


class TestPersonaFromSource(unittest.TestCase):
    def test_from_source_populates_all_sections(self):
        source = InlinePersonaSource(soul="S", style="T", agents="A")
        persona = Persona.from_source(source)
        self.assertEqual(persona.soul, "S")
        self.assertEqual(persona.style, "T")
        self.assertEqual(persona.agents, "A")

    def test_from_source_records_backend_class_name(self):
        persona = Persona.from_source(InlinePersonaSource(soul="x"))
        self.assertEqual(persona.source, "InlinePersonaSource")

    def test_from_source_compose(self):
        source = InlinePersonaSource(soul="I am.", agents="Rule.")
        persona = Persona.from_source(source)
        self.assertIn("I am.", persona.compose())
        self.assertIn("Rule.", persona.compose())

    def test_from_source_with_filesystem_matches_from_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SOUL.md").write_text("same", encoding="utf-8")
            (Path(tmpdir) / "STYLE.md").write_text("content", encoding="utf-8")
            via_dir = Persona.from_dir(tmpdir)
            via_source = Persona.from_source(FilesystemPersonaSource(tmpdir))
            self.assertEqual(via_dir.soul, via_source.soul)
            self.assertEqual(via_dir.style, via_source.style)
            self.assertEqual(via_dir.agents, via_source.agents)

    def test_from_dir_still_records_directory_path_as_source(self):
        """from_dir legacy behavior: persona.source is the resolved directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SOUL.md").write_text("x", encoding="utf-8")
            persona = Persona.from_dir(tmpdir)
            self.assertEqual(persona.source, str(Path(tmpdir).resolve()))


class TestBaseAgentPersonaSourceIntegration(unittest.TestCase):
    def test_accepts_persona_source(self):
        from openbench.intelligence.base import BaseAgent

        source = InlinePersonaSource(soul="I am a test agent.")
        agent = BaseAgent(goal="test", persona=source)
        self.assertIsNotNone(agent._persona)
        self.assertEqual(agent._persona.soul, "I am a test agent.")
        self.assertIn("I am a test agent.", agent._system_prompt)

    def test_persona_source_overrides_system_prompt_with_warning(self):
        import warnings

        from openbench.intelligence.base import BaseAgent

        source = InlinePersonaSource(agents="rule")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            agent = BaseAgent(
                goal="test",
                persona=source,
                system_prompt="ignored",
            )
            user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
            self.assertTrue(user_warnings)
        self.assertIn("rule", agent._system_prompt)
        self.assertNotIn("ignored", agent._system_prompt)

    def test_invalid_persona_type_mentions_persona_source(self):
        from openbench.intelligence.base import BaseAgent

        with self.assertRaises(TypeError) as ctx:
            BaseAgent(goal="test", persona=123)
        self.assertIn("PersonaSource", str(ctx.exception))


class TestLocalBackendPersonaSource(unittest.TestCase):
    def setUp(self):
        from openbench.core.storage import LocalStorageBackend

        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.backend = LocalStorageBackend(self.root)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_default_name_creates_personas_default_dir(self):
        source = self.backend.persona_source()
        self.assertIsInstance(source, FilesystemPersonaSource)
        self.assertTrue((self.root / "personas" / "default").is_dir())

    def test_custom_name_creates_distinct_subdir(self):
        self.backend.persona_source("lci-analyst")
        self.assertTrue((self.root / "personas" / "lci-analyst").is_dir())

    def test_source_reads_files_written_to_directory(self):
        source = self.backend.persona_source("code-reviewer")
        (self.root / "personas" / "code-reviewer" / "SOUL.md").write_text(
            "I review Python diligently.", encoding="utf-8"
        )
        persona = Persona.from_source(source)
        self.assertEqual(persona.soul, "I review Python diligently.")

    def test_multiple_personas_are_independent(self):
        a = self.backend.persona_source("a")
        b = self.backend.persona_source("b")
        (self.root / "personas" / "a" / "SOUL.md").write_text("A", encoding="utf-8")
        (self.root / "personas" / "b" / "SOUL.md").write_text("B", encoding="utf-8")
        self.assertEqual(a.fetch("soul"), "A")
        self.assertEqual(b.fetch("soul"), "B")


if __name__ == "__main__":
    unittest.main()
