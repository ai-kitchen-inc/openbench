"""End-to-end: memory-scratchpad skill → GoogleDriveStorageBackend.

Exercises the full path that Lici takes when she calls the
``write_memory`` / ``read_memory`` / ``list_memory_keys`` tools:

    skill.bind(scratchpad=store)
    └── write_memory(key, content)
        └── ScratchpadStore.write(key, content)
            └── GoogleDriveScratchpad.write(...)
                └── Drive API files().create/update (mocked)

The Drive REST layer is stubbed with a fake ``service`` object so no
network happens. The FakeDrive state is inspected after each tool
call to prove the data actually reached the "Drive" side of the
contract — catching regressions where the skill rebinds to a local
store, or where the ScratchpadStore Protocol drifts.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import openbench
from openbench.integrations.firebase_auth import build_credentials
from openbench.integrations.gdrive import GoogleDriveStorageBackend
from openbench.intelligence.skill import Skill

_FOLDER_MIME = "application/vnd.google-apps.folder"
_FILE_MIME = "text/markdown"


class FakeDrive:
    """In-memory Drive that records every files().create / update / get_media.

    Tracks:
    - folders: {name → id} keyed by parent path
    - files:   {(parent_id, name) → (id, content)}

    Good enough for scratchpad + backend folder resolution; does NOT
    model the full Drive API.
    """

    def __init__(self):
        self._folders: dict[tuple[str, str], str] = {}
        # (parent_id, name) → (file_id, content)
        self._files: dict[tuple[str, str], tuple[str, str]] = {}
        self._next_id = 1

    def _mint(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def ensure_folder(self, parent_id: str, name: str) -> str:
        key = (parent_id, name)
        if key not in self._folders:
            self._folders[key] = self._mint("folder")
        return self._folders[key]

    def build_service(self) -> Any:
        """Return a MagicMock-shaped service.files() that proxies to us."""
        fake = MagicMock()

        def _list(**kwargs):
            q = kwargs["q"]

            # Parse the fragments Drive queries actually use: parent,
            # name, mimeType. Order in the WHERE clause is fixed by our
            # codebase, but we're lenient about optional clauses.
            parent_m = re.search(r"'([^']+)' in parents", q)
            name_m = re.search(r"name = '([^']+)'", q)
            mime_m = re.search(r"mimeType = '([^']+)'", q)
            parent_id = parent_m.group(1) if parent_m else None
            name = name_m.group(1) if name_m else None
            mime = mime_m.group(1) if mime_m else None

            # Folder-by-name query.
            if parent_id and name and mime == _FOLDER_MIME:
                fid = self._folders.get((parent_id, name))
                res = [{"id": fid, "name": name}] if fid else []
                return MagicMock(execute=MagicMock(return_value={"files": res}))

            # File-by-name query. Scratchpad doesn't include a mimeType
            # clause, so we match on (parent, name) with `.md` suffix.
            if parent_id and name:
                hit = self._files.get((parent_id, name))
                if hit is not None:
                    return MagicMock(
                        execute=MagicMock(
                            return_value={"files": [{"id": hit[0], "name": name}]}
                        )
                    )
                return MagicMock(execute=MagicMock(return_value={"files": []}))

            # "List all files in folder" — used by list_keys().
            if parent_id:
                results = [
                    {"name": fname}
                    for (pid, fname), _ in self._files.items()
                    if pid == parent_id
                ]
                return MagicMock(execute=MagicMock(return_value={"files": results}))

            return MagicMock(execute=MagicMock(return_value={"files": []}))

        def _create(**kwargs):
            body = kwargs["body"]
            parent_id = body["parents"][0]
            name = body["name"]
            mime = body["mimeType"]

            if mime == _FOLDER_MIME:
                fid = self.ensure_folder(parent_id, name)
                return MagicMock(execute=MagicMock(return_value={"id": fid}))

            # File create — upload media.
            media = kwargs.get("media_body")
            # MediaInMemoryUpload exposes ._body in modern google-api-python-client.
            content = b""
            if media is not None:
                content = getattr(media, "_body", None) or media.getbytes(0, -1)
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
            fid = self._mint("file")
            self._files[(parent_id, name)] = (fid, content)
            return MagicMock(execute=MagicMock(return_value={"id": fid}))

        def _update(**kwargs):
            file_id = kwargs["fileId"]
            media = kwargs.get("media_body")
            content = b""
            if media is not None:
                content = getattr(media, "_body", None) or media.getbytes(0, -1)
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
            for key, (fid, _) in self._files.items():
                if fid == file_id:
                    self._files[key] = (fid, content)
                    break
            return MagicMock(execute=MagicMock(return_value={"id": file_id}))

        def _get_media(fileId: str):
            for (_pid, _name), (fid, content) in self._files.items():
                if fid == fileId:
                    return MagicMock(execute=MagicMock(return_value=content.encode("utf-8")))
            return MagicMock(execute=MagicMock(return_value=b""))

        def _delete(**kwargs):
            fid = kwargs["fileId"]
            for key, (saved, _) in list(self._files.items()):
                if saved == fid:
                    del self._files[key]
                    break
            return MagicMock(execute=MagicMock(return_value=None))

        files = MagicMock()
        files.list = MagicMock(side_effect=_list)
        files.create = MagicMock(side_effect=_create)
        files.update = MagicMock(side_effect=_update)
        files.get_media = MagicMock(side_effect=_get_media)
        files.delete = MagicMock(side_effect=_delete)
        fake.files = MagicMock(return_value=files)
        return fake


class TestMemorySkillDriveEndToEnd(unittest.TestCase):
    """Exercise the memory-scratchpad skill against a Drive-backed store."""

    def setUp(self):
        self.drive = FakeDrive()
        # Pre-create the "OpenBench" root folder the backend expects.
        self._root_id = self.drive.ensure_folder("root", "OpenBench")

        self.backend = GoogleDriveStorageBackend(
            root_folder_id=self._root_id,
            credentials=build_credentials(
                refresh_token="fake-refresh",
                client_id="client.apps.googleusercontent.com",
                client_secret="s3cret",
                scopes=["https://www.googleapis.com/auth/drive.file"],
            ),
        )

        # Short-circuit the real discovery.build() call so no
        # google-api-python-client is touched — both the backend (for
        # folder resolution) and the scratchpad store (for file ops)
        # share the FakeDrive service.
        import openbench.integrations.gdrive.backend as backend_mod
        import openbench.integrations.gdrive.scratchpad as scratchpad_mod

        orig_backend_build = backend_mod.GoogleDriveStorageBackend._build_service
        orig_scratchpad_build = scratchpad_mod.GoogleDriveScratchpad._build_service

        backend_mod.GoogleDriveStorageBackend._build_service = (
            lambda _s: self.drive.build_service()
        )
        scratchpad_mod.GoogleDriveScratchpad._build_service = (
            lambda _s: self.drive.build_service()
        )

        def _restore():
            backend_mod.GoogleDriveStorageBackend._build_service = orig_backend_build
            scratchpad_mod.GoogleDriveScratchpad._build_service = orig_scratchpad_build

        self.addCleanup(_restore)

        # Grab a scratchpad and feed it to the skill.
        self.scratchpad = self.backend.scratchpad_store()

        # Load the memory-scratchpad skill directly from its source
        # directory (no registry, so no collision with other tests that
        # may have loaded the same skill into a module-level state).
        openbench_pkg_root = Path(openbench.__file__).parent
        skill_dir = openbench_pkg_root / "skills" / "memory-scratchpad"
        self.skill = Skill.from_dir(skill_dir)
        bound = self.skill.bind(scratchpad=self.scratchpad)
        self.assertTrue(bound, "memory-scratchpad should expose a bind() hook")

        # Reference the module the loader placed in sys.modules so we can
        # call tool callables the same way ToolExecutor does.
        import sys as _sys

        self.tools_mod = _sys.modules["openbench_skill_memory_scratchpad"]

    # ------------------------------------------------------------------ tests

    def test_write_then_read_round_trip(self):
        confirm = self.tools_mod.write_memory("preferences", "# LCA prefs\n- GWP100")
        self.assertIn("wrote", confirm)

        # Verify the call actually landed in FakeDrive.
        memory_folder_id = self.drive._folders.get((self._root_id, "memory"))
        self.assertIsNotNone(memory_folder_id)
        self.assertIn((memory_folder_id, "preferences.md"), self.drive._files)
        _fid, saved_content = self.drive._files[(memory_folder_id, "preferences.md")]
        self.assertIn("GWP100", saved_content)

        # Read it back via the skill's tool.
        readback = self.tools_mod.read_memory("preferences")
        self.assertEqual(readback, "# LCA prefs\n- GWP100")

    def test_append_extends_existing_content(self):
        self.tools_mod.write_memory("notes", "line 1")
        self.tools_mod.append_memory("notes", "line 2")
        self.tools_mod.append_memory("notes", "line 3")

        content = self.tools_mod.read_memory("notes")
        # Separator logic matches LocalMarkdownScratchpad — newline between blocks.
        self.assertEqual(content, "line 1\nline 2\nline 3")

    def test_list_memory_keys_returns_all_written(self):
        self.tools_mod.write_memory("alpha", "A")
        self.tools_mod.write_memory("beta", "B")
        self.tools_mod.write_memory("gamma", "G")
        keys = self.tools_mod.list_memory_keys()
        self.assertEqual(sorted(keys), ["alpha", "beta", "gamma"])

    def test_read_missing_key_returns_empty(self):
        self.assertEqual(self.tools_mod.read_memory("nothing-written-yet"), "")

    def test_overwrite_replaces_content(self):
        self.tools_mod.write_memory("k", "v1")
        self.tools_mod.write_memory("k", "v2")
        self.assertEqual(self.tools_mod.read_memory("k"), "v2")
        # Still just one file per key on Drive.
        mem_folder = self.drive._folders[(self._root_id, "memory")]
        md_files = [k for (pid, name), _ in self.drive._files.items() if pid == mem_folder for k in [name]]
        self.assertEqual(md_files.count("k.md"), 1)

    def test_skill_not_bound_raises_actionable_error(self):
        # Re-binding with None simulates a misconfigured agent.
        self.skill.bind(scratchpad=None)
        with self.assertRaises(RuntimeError) as ctx:
            self.tools_mod.read_memory("k")
        self.assertIn("not bound", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
