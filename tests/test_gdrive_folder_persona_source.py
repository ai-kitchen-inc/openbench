"""Tests for :class:`GoogleDrivePersonaSource` (folder variant).

Mocks the Drive API so no gdrive extras are needed to run.
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.integrations.gdrive import GoogleDrivePersonaSource
from openbench.intelligence.persona import Persona

# ---------------------------------------------------------------------------
# Fake Drive service helpers
# ---------------------------------------------------------------------------


def _build_fake_service(file_contents: dict[str, str]) -> MagicMock:
    """Build a MagicMock Drive service that returns ``file_contents`` keyed by filename.

    ``files.list`` returns the matching file_id (or empty) based on the
    ``name=`` clause in the query string; ``files.get_media`` returns
    the raw UTF-8 bytes for that file id.
    """
    service = MagicMock()

    # Each filename gets a synthetic id derived from itself so we can
    # round-trip list → get_media without maintaining a separate map.
    def _list_impl(**kwargs: Any) -> Any:
        q = kwargs.get("q", "")
        for name in file_contents:
            # Query looks like: "'<folder>' in parents and name = 'SOUL.md' and ..."
            needle = f"name = '{name}'"
            if needle in q:
                resp = MagicMock()
                resp.execute.return_value = {
                    "files": [{"id": f"id-{name}", "name": name, "mimeType": "text/markdown"}]
                }
                return resp
        resp = MagicMock()
        resp.execute.return_value = {"files": []}
        return resp

    def _get_media_impl(fileId: str) -> Any:
        # Recover filename from synthetic id
        fname = fileId[len("id-") :]
        body = file_contents.get(fname, "")
        resp = MagicMock()
        resp.execute.return_value = body.encode("utf-8")
        return resp

    service.files.return_value.list.side_effect = _list_impl
    service.files.return_value.get_media.side_effect = _get_media_impl
    return service


def _source_with_files(file_contents: dict[str, str], **kwargs: Any) -> GoogleDrivePersonaSource:
    source = GoogleDrivePersonaSource(
        folder_id="folder-abc",
        service_account_file="/fake/creds.json",
        **kwargs,
    )
    source._service = _build_fake_service(file_contents)
    return source


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_requires_folder_id(self):
        with self.assertRaises(ValueError):
            GoogleDrivePersonaSource(
                folder_id="",
                service_account_file="/fake/creds.json",
            )

    def test_requires_auth(self):
        with self.assertRaises(ValueError):
            GoogleDrivePersonaSource(folder_id="f")

    def test_accepts_service_account_file(self):
        src = GoogleDrivePersonaSource(folder_id="f", service_account_file="/x")
        self.assertEqual(src.folder_id, "f")

    def test_accepts_explicit_credentials(self):
        src = GoogleDrivePersonaSource(folder_id="f", credentials=object())
        self.assertEqual(src.folder_id, "f")

    def test_construction_is_offline(self):
        """No network / no googleapiclient import during construction."""
        GoogleDrivePersonaSource(folder_id="f", service_account_file="/x")

    def test_repr_includes_folder_id(self):
        src = GoogleDrivePersonaSource(folder_id="my-folder", service_account_file="/x")
        self.assertIn("my-folder", repr(src))


class TestMissingDependency(unittest.TestCase):
    def test_lazy_build_raises_import_error_with_install_hint(self):
        src = GoogleDrivePersonaSource(folder_id="f", service_account_file="/x")
        with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
            with self.assertRaises(ImportError) as ctx:
                src._build_service()
            self.assertIn("pip install openbench[gdrive]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Fetch behavior
# ---------------------------------------------------------------------------


class TestFetch(unittest.TestCase):
    def test_reads_all_three_files(self):
        src = _source_with_files(
            {
                "SOUL.md": "I am an LCA analyst.",
                "STYLE.md": "Indonesian by default.",
                "AGENTS.md": "Call xql_catalog first.",
            }
        )
        self.assertEqual(src.fetch("soul"), "I am an LCA analyst.")
        self.assertEqual(src.fetch("style"), "Indonesian by default.")
        self.assertEqual(src.fetch("agents"), "Call xql_catalog first.")

    def test_missing_file_returns_empty_string(self):
        src = _source_with_files({"SOUL.md": "soul only"})
        self.assertEqual(src.fetch("soul"), "soul only")
        self.assertEqual(src.fetch("style"), "")
        self.assertEqual(src.fetch("agents"), "")

    def test_strips_trailing_whitespace(self):
        src = _source_with_files({"SOUL.md": "   content with pad   \n\n"})
        self.assertEqual(src.fetch("soul"), "content with pad")

    def test_unknown_key_returns_empty(self):
        src = _source_with_files({"SOUL.md": "x"})
        self.assertEqual(src.fetch("unknown"), "")

    def test_str_response_is_accepted(self):
        """Some gapi configurations return text instead of bytes."""
        src = _source_with_files({"SOUL.md": "plain string"})
        # Patch get_media's execute to return a str (not bytes)
        src._service.files.return_value.get_media.side_effect = lambda fileId: MagicMock(
            execute=MagicMock(return_value="plain string")
        )
        self.assertEqual(src.fetch("soul"), "plain string")

    def test_list_query_uses_folder_id_and_filename(self):
        """Each fetched section triggers a list() with a focused query."""
        src = _source_with_files({"SOUL.md": "x"})
        src.fetch("soul")  # triggers fetching all three section files
        queries = [call.kwargs["q"] for call in src._service.files.return_value.list.call_args_list]
        combined = " | ".join(queries)
        self.assertIn("folder-abc", combined)
        # Each canonical section file must appear in at least one query
        for filename in ("SOUL.md", "STYLE.md", "AGENTS.md"):
            self.assertIn(filename, combined)
        self.assertTrue(all("trashed = false" in q for q in queries))

    def test_supports_shared_drives_flags(self):
        src = _source_with_files({"SOUL.md": "x"})
        src.fetch("soul")
        for call in src._service.files.return_value.list.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)
            self.assertIs(call.kwargs["includeItemsFromAllDrives"], True)


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


class TestCache(unittest.TestCase):
    def test_repeated_fetch_uses_cache(self):
        src = _source_with_files(
            {"SOUL.md": "x", "STYLE.md": "y", "AGENTS.md": "z"},
            cache_ttl=300.0,
        )
        for _ in range(3):
            src.fetch("soul")
            src.fetch("style")
            src.fetch("agents")
        # One list+get_media PAIR per section = 3 list calls across all fetches
        self.assertEqual(src._service.files.return_value.list.call_count, 3)

    def test_refresh_invalidates(self):
        src = _source_with_files({"SOUL.md": "x"}, cache_ttl=300.0)
        src.fetch("soul")
        src.refresh()
        src.fetch("soul")
        # Each fetch fetches all 3 sections → 3 list calls per cycle, 2 cycles = 6
        self.assertEqual(src._service.files.return_value.list.call_count, 6)

    def test_ttl_zero_always_fetches(self):
        src = _source_with_files({"SOUL.md": "x"}, cache_ttl=0.0)
        src.fetch("soul")
        src.fetch("soul")
        # ttl=0 means every fetch re-reads all 3 files
        self.assertEqual(src._service.files.return_value.list.call_count, 6)

    def test_ttl_expiry_triggers_refetch(self):
        src = _source_with_files({"SOUL.md": "x"}, cache_ttl=0.01)
        src.fetch("soul")
        time.sleep(0.02)
        src.fetch("soul")
        self.assertEqual(src._service.files.return_value.list.call_count, 6)


class TestPersonaIntegration(unittest.TestCase):
    def test_persona_from_source_composes(self):
        src = _source_with_files(
            {
                "SOUL.md": "I am Lici.",
                "STYLE.md": "Bilingual.",
                "AGENTS.md": "Verify first.",
            }
        )
        persona = Persona.from_source(src)
        self.assertEqual(persona.soul, "I am Lici.")
        self.assertEqual(persona.style, "Bilingual.")
        self.assertEqual(persona.agents, "Verify first.")
        self.assertEqual(persona.source, "GoogleDrivePersonaSource")


if __name__ == "__main__":
    unittest.main()
