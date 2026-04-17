"""Tests for :class:`GoogleDocPersonaSource`.

Uses a fake Google Docs API response so the tests run without the
``[gdrive]`` extras installed. The only time we touch the lazy imports
is the missing-dep test, which exercises the helpful error path.
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.integrations.gdrive import GoogleDocPersonaSource
from openbench.intelligence.persona import Persona
from openbench.intelligence.persona_source import PersonaSource

# ---------------------------------------------------------------------------
# Helpers to build fake Google Docs API payloads
# ---------------------------------------------------------------------------


def _para(text: str, style: str = "NORMAL_TEXT", bullet: bool = False) -> dict[str, Any]:
    para: dict[str, Any] = {
        "paragraphStyle": {"namedStyleType": style},
        "elements": [{"textRun": {"content": text + "\n"}}],
    }
    if bullet:
        para["bullet"] = {"listId": "kix.list-1"}
    return {"paragraph": para}


def _doc(*paragraphs: dict[str, Any]) -> dict[str, Any]:
    return {"body": {"content": list(paragraphs)}}


def _source_with_fake_doc(doc: dict[str, Any], **kwargs: Any) -> GoogleDocPersonaSource:
    """Build a source whose API is pre-mocked to return ``doc``."""
    source = GoogleDocPersonaSource(
        doc_id="doc-abc",
        service_account_file="/fake/creds.json",
        **kwargs,
    )
    mock_service = MagicMock()
    mock_service.documents().get().execute.return_value = doc
    source._service = mock_service
    return source


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_requires_doc_id(self):
        with self.assertRaises(ValueError):
            GoogleDocPersonaSource(
                doc_id="",
                service_account_file="/fake/creds.json",
            )

    def test_requires_auth(self):
        with self.assertRaises(ValueError):
            GoogleDocPersonaSource(doc_id="x")

    def test_accepts_service_account_file(self):
        src = GoogleDocPersonaSource(doc_id="abc", service_account_file="/fake/creds.json")
        self.assertEqual(src.doc_id, "abc")

    def test_accepts_explicit_credentials(self):
        src = GoogleDocPersonaSource(doc_id="abc", credentials=object())
        self.assertEqual(src.doc_id, "abc")

    def test_construction_does_not_touch_network(self):
        """Building a source must NOT import googleapiclient or hit the API."""
        GoogleDocPersonaSource(doc_id="abc", service_account_file="/fake/creds.json")

    def test_repr_includes_doc_id(self):
        src = GoogleDocPersonaSource(doc_id="abc", service_account_file="/x")
        self.assertIn("abc", repr(src))


# ---------------------------------------------------------------------------
# Missing deps produce a useful ImportError
# ---------------------------------------------------------------------------


class TestMissingDependency(unittest.TestCase):
    def test_lazy_build_raises_import_error_with_install_hint(self):
        src = GoogleDocPersonaSource(doc_id="abc", service_account_file="/fake/creds.json")
        # Simulate googleapiclient.discovery.build raising ImportError
        # when the helper tries to import it lazily.
        with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
            # Force the real _build_service to run the import statement,
            # which will now fail.
            with self.assertRaises(ImportError) as ctx:
                src._build_service()
            self.assertIn("pip install openbench[gdrive]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Doc parsing — H1 headings split into sections
# ---------------------------------------------------------------------------


class TestParsing(unittest.TestCase):
    def test_parses_all_three_canonical_h1_headings(self):
        doc = _doc(
            _para("SOUL", "HEADING_1"),
            _para("I am an LCA analyst."),
            _para("STYLE", "HEADING_1"),
            _para("Reply in Indonesian."),
            _para("AGENTS", "HEADING_1"),
            _para("Always call xql_catalog first."),
        )
        src = _source_with_fake_doc(doc)
        self.assertEqual(src.fetch("soul"), "I am an LCA analyst.")
        self.assertEqual(src.fetch("style"), "Reply in Indonesian.")
        self.assertEqual(src.fetch("agents"), "Always call xql_catalog first.")

    def test_headings_are_case_insensitive(self):
        doc = _doc(
            _para("soul", "HEADING_1"),
            _para("lower-case marker."),
            _para("Style", "HEADING_1"),
            _para("mixed case marker."),
        )
        src = _source_with_fake_doc(doc)
        self.assertEqual(src.fetch("soul"), "lower-case marker.")
        self.assertEqual(src.fetch("style"), "mixed case marker.")

    def test_trailing_colon_in_header_is_tolerated(self):
        """Google Docs often auto-adds ':' after pasted headers."""
        doc = _doc(
            _para("SOUL:", "HEADING_1"),
            _para("still soul"),
        )
        src = _source_with_fake_doc(doc)
        self.assertEqual(src.fetch("soul"), "still soul")

    def test_missing_sections_return_empty_string(self):
        doc = _doc(
            _para("SOUL", "HEADING_1"),
            _para("only soul section"),
        )
        src = _source_with_fake_doc(doc)
        self.assertEqual(src.fetch("soul"), "only soul section")
        self.assertEqual(src.fetch("style"), "")
        self.assertEqual(src.fetch("agents"), "")

    def test_unknown_key_returns_empty(self):
        doc = _doc(_para("SOUL", "HEADING_1"), _para("content"))
        src = _source_with_fake_doc(doc)
        self.assertEqual(src.fetch("unknown"), "")

    def test_no_matching_h1_falls_back_to_agents(self):
        """Document with no SOUL/STYLE/AGENTS H1 → whole body is 'agents'."""
        doc = _doc(
            _para("Introduction", "HEADING_1"),
            _para("This agent follows rules R1, R2, R3."),
        )
        src = _source_with_fake_doc(doc)
        self.assertEqual(src.fetch("soul"), "")
        self.assertEqual(src.fetch("style"), "")
        self.assertIn("Introduction", src.fetch("agents"))
        self.assertIn("R1, R2, R3", src.fetch("agents"))

    def test_h2_inside_section_becomes_markdown_heading(self):
        doc = _doc(
            _para("SOUL", "HEADING_1"),
            _para("Values", "HEADING_2"),
            _para("- Accuracy over speed"),
        )
        src = _source_with_fake_doc(doc)
        soul = src.fetch("soul")
        self.assertIn("## Values", soul)
        self.assertIn("Accuracy over speed", soul)

    def test_bullet_paragraphs_become_markdown_bullets(self):
        doc = _doc(
            _para("AGENTS", "HEADING_1"),
            _para("First rule", bullet=True),
            _para("Second rule", bullet=True),
        )
        src = _source_with_fake_doc(doc)
        agents = src.fetch("agents")
        self.assertIn("- First rule", agents)
        self.assertIn("- Second rule", agents)

    def test_non_matching_h1_inside_section_is_preserved(self):
        doc = _doc(
            _para("SOUL", "HEADING_1"),
            _para("Overview", "HEADING_1"),  # not a canonical section
            _para("retained"),
        )
        src = _source_with_fake_doc(doc)
        soul = src.fetch("soul")
        self.assertIn("# Overview", soul)
        self.assertIn("retained", soul)

    def test_empty_doc_yields_all_empty(self):
        src = _source_with_fake_doc(_doc())
        for key in PersonaSource.KEYS:
            self.assertEqual(src.fetch(key), "")


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


class TestCache(unittest.TestCase):
    def test_repeated_fetch_uses_cache(self):
        doc = _doc(_para("SOUL", "HEADING_1"), _para("cached"))
        src = _source_with_fake_doc(doc, cache_ttl=300.0)
        src.fetch("soul")
        src.fetch("style")
        src.fetch("agents")
        # Only one API call regardless of how many fetches
        self.assertEqual(src._service.documents().get().execute.call_count, 1)

    def test_refresh_invalidates_cache(self):
        doc = _doc(_para("SOUL", "HEADING_1"), _para("first"))
        src = _source_with_fake_doc(doc, cache_ttl=300.0)
        src.fetch("soul")
        self.assertEqual(src._service.documents().get().execute.call_count, 1)

        src.refresh()
        src.fetch("soul")
        self.assertEqual(src._service.documents().get().execute.call_count, 2)

    def test_ttl_zero_always_fetches(self):
        doc = _doc(_para("SOUL", "HEADING_1"), _para("live"))
        src = _source_with_fake_doc(doc, cache_ttl=0.0)
        src.fetch("soul")
        src.fetch("soul")
        self.assertEqual(src._service.documents().get().execute.call_count, 2)

    def test_ttl_expiry_triggers_refetch(self):
        doc = _doc(_para("SOUL", "HEADING_1"), _para("x"))
        src = _source_with_fake_doc(doc, cache_ttl=0.01)
        src.fetch("soul")
        time.sleep(0.02)
        src.fetch("soul")
        self.assertEqual(src._service.documents().get().execute.call_count, 2)


# ---------------------------------------------------------------------------
# Integration with Persona.from_source
# ---------------------------------------------------------------------------


class TestPersonaIntegration(unittest.TestCase):
    def test_persona_from_source_composes_all_sections(self):
        doc = _doc(
            _para("SOUL", "HEADING_1"),
            _para("I am Lici."),
            _para("STYLE", "HEADING_1"),
            _para("I speak Indonesian."),
            _para("AGENTS", "HEADING_1"),
            _para("Always verify first."),
        )
        src = _source_with_fake_doc(doc)
        persona = Persona.from_source(src)

        self.assertEqual(persona.soul, "I am Lici.")
        self.assertEqual(persona.style, "I speak Indonesian.")
        self.assertEqual(persona.agents, "Always verify first.")
        self.assertEqual(persona.source, "GoogleDocPersonaSource")
        composed = persona.compose()
        self.assertIn("I am Lici.", composed)
        self.assertIn("I speak Indonesian.", composed)
        self.assertIn("Always verify first.", composed)


if __name__ == "__main__":
    unittest.main()
