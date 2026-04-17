"""Tests for :class:`GoogleDriveScratchpad`.

All tests mock the Drive API so ``[gdrive]`` extras are not required to
run the suite. One test patches ``googleapiclient.http`` so we don't
need MediaInMemoryUpload either.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.integrations.gdrive import GoogleDriveScratchpad

# ---------------------------------------------------------------------------
# Fake Drive service — a tiny in-memory file store mimicking the gapi surface
# ---------------------------------------------------------------------------


class FakeDrive:
    """In-memory fake of the Drive v3 service for a single folder.

    Tracks files as ``{file_id: {"name": str, "content": bytes}}`` so
    list/get_media/create/update/delete round-trip correctly.
    """

    def __init__(self, folder_id: str = "folder-abc"):
        self.folder_id = folder_id
        self.files_by_id: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        # Track call counts for assertions
        self.list_calls = 0
        self.get_media_calls = 0
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0

    # --- public helpers -----------------------------------------------------

    def seed(self, name: str, content: str) -> str:
        file_id = self._mint_id()
        self.files_by_id[file_id] = {
            "name": name,
            "content": content.encode("utf-8"),
        }
        return file_id

    def names(self) -> list[str]:
        return sorted(meta["name"] for meta in self.files_by_id.values())

    def content_for(self, name: str) -> str:
        for meta in self.files_by_id.values():
            if meta["name"] == name:
                return meta["content"].decode("utf-8")
        return ""

    def _mint_id(self) -> str:
        fid = f"id-{self._next_id}"
        self._next_id += 1
        return fid

    # --- gapi-shaped surface -----------------------------------------------

    def files(self) -> MagicMock:
        svc = MagicMock()
        svc.list.side_effect = self._list
        svc.get_media.side_effect = self._get_media
        svc.create.side_effect = self._create
        svc.update.side_effect = self._update
        svc.delete.side_effect = self._delete
        return svc

    def _list(self, **kwargs: Any) -> Any:
        self.list_calls += 1
        import re

        q = kwargs.get("q", "")
        # Two query shapes matter:
        #   1. ``name = 'foo.md'``  — find a single file by name
        #   2. ``mimeType = '...'`` — list all markdown files in folder
        name_match = re.search(r"name = '([^']+)'", q)
        if name_match is not None:
            needle = name_match.group(1)
            matches = [
                {"id": fid, "name": meta["name"]}
                for fid, meta in self.files_by_id.items()
                if meta["name"] == needle
            ]
        else:
            # No name filter — return every .md file we hold.
            matches = [
                {"id": fid, "name": meta["name"]}
                for fid, meta in self.files_by_id.items()
                if meta["name"].endswith(".md")
            ]
        resp = MagicMock()
        resp.execute.return_value = {"files": matches}
        return resp

    def _get_media(self, fileId: str) -> Any:
        self.get_media_calls += 1
        meta = self.files_by_id.get(fileId)
        resp = MagicMock()
        resp.execute.return_value = meta["content"] if meta else b""
        return resp

    def _create(self, body: dict[str, Any], media_body: Any, **_: Any) -> Any:
        self.create_calls += 1
        fid = self._mint_id()
        self.files_by_id[fid] = {
            "name": body["name"],
            "content": media_body.body_bytes,
        }
        resp = MagicMock()
        resp.execute.return_value = {"id": fid}
        return resp

    def _update(self, fileId: str, media_body: Any, **_: Any) -> Any:
        self.update_calls += 1
        if fileId in self.files_by_id:
            self.files_by_id[fileId]["content"] = media_body.body_bytes
        resp = MagicMock()
        resp.execute.return_value = {"id": fileId}
        return resp

    def _delete(self, fileId: str, **_: Any) -> Any:
        self.delete_calls += 1
        self.files_by_id.pop(fileId, None)
        resp = MagicMock()
        resp.execute.return_value = None
        return resp


class FakeMedia:
    """Stand-in for MediaInMemoryUpload — just holds the bytes."""

    def __init__(self, body: bytes, mimetype: str = "text/markdown"):
        self.body_bytes = body
        self.mimetype = mimetype


def _make_pad(fake: FakeDrive) -> GoogleDriveScratchpad:
    pad = GoogleDriveScratchpad(
        folder_id=fake.folder_id,
        service_account_file="/fake/creds.json",
    )
    service = MagicMock()
    service.files.side_effect = fake.files
    pad._service = service
    # Patch the media factory on the instance so create/update work without
    # googleapiclient installed.
    pad._media = lambda content: FakeMedia(content.encode("utf-8"))  # type: ignore[method-assign]
    return pad


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_requires_folder_id(self):
        with self.assertRaises(ValueError):
            GoogleDriveScratchpad(folder_id="", service_account_file="/x")

    def test_requires_auth(self):
        with self.assertRaises(ValueError):
            GoogleDriveScratchpad(folder_id="f")

    def test_accepts_service_account_file(self):
        pad = GoogleDriveScratchpad(folder_id="f", service_account_file="/x")
        self.assertEqual(pad.folder_id, "f")

    def test_accepts_explicit_credentials(self):
        pad = GoogleDriveScratchpad(folder_id="f", credentials=object())
        self.assertEqual(pad.folder_id, "f")

    def test_construction_is_offline(self):
        GoogleDriveScratchpad(folder_id="f", service_account_file="/x")

    def test_repr_includes_folder_id(self):
        pad = GoogleDriveScratchpad(folder_id="demo-folder", service_account_file="/x")
        self.assertIn("demo-folder", repr(pad))


class TestMissingDependency(unittest.TestCase):
    def test_lazy_build_service_raises_with_install_hint(self):
        pad = GoogleDriveScratchpad(folder_id="f", service_account_file="/x")
        with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
            with self.assertRaises(ImportError) as ctx:
                pad._build_service()
            self.assertIn("pip install openbench[gdrive]", str(ctx.exception))


class TestKeyValidation(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.pad = _make_pad(self.fake)

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            self.pad.read("")

    def test_slash_key_rejected(self):
        with self.assertRaises(ValueError):
            self.pad.write("projects/q1", "x")

    def test_backslash_key_rejected(self):
        with self.assertRaises(ValueError):
            self.pad.delete("foo\\bar")

    def test_nul_byte_rejected(self):
        with self.assertRaises(ValueError):
            self.pad.read("bad\x00key")


# ---------------------------------------------------------------------------
# read / write / append / list / delete
# ---------------------------------------------------------------------------


class TestReadWrite(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.pad = _make_pad(self.fake)

    def test_read_missing_key_returns_empty(self):
        self.assertEqual(self.pad.read("nope"), "")

    def test_write_creates_new_file(self):
        self.pad.write("default", "hello")
        self.assertEqual(self.fake.names(), ["default.md"])
        self.assertEqual(self.fake.content_for("default.md"), "hello")
        self.assertEqual(self.fake.create_calls, 1)

    def test_write_overwrites_existing(self):
        self.pad.write("k", "v1")
        self.pad.write("k", "v2")
        self.assertEqual(self.fake.content_for("k.md"), "v2")
        self.assertEqual(self.fake.update_calls, 1)
        # Only one create (on first write)
        self.assertEqual(self.fake.create_calls, 1)

    def test_read_after_write_roundtrip(self):
        self.pad.write("k", "roundtrip")
        self.assertEqual(self.pad.read("k"), "roundtrip")

    def test_write_then_read_preserves_unicode(self):
        self.pad.write("k", "Halo dunia — 你好 🌍")
        self.assertEqual(self.pad.read("k"), "Halo dunia — 你好 🌍")


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.pad = _make_pad(self.fake)

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


class TestListKeys(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.pad = _make_pad(self.fake)

    def test_empty_folder_returns_empty_list(self):
        self.assertEqual(self.pad.list_keys(), [])

    def test_list_keys_sorted(self):
        self.pad.write("zeta", "")
        self.pad.write("alpha", "")
        self.pad.write("mu", "")
        self.assertEqual(self.pad.list_keys(), ["alpha", "mu", "zeta"])

    def test_list_keys_strips_md_extension(self):
        self.pad.write("preferences", "data")
        self.assertEqual(self.pad.list_keys(), ["preferences"])

    def test_list_keys_ignores_non_md_files(self):
        # Manually inject a non-md file into the fake drive
        self.fake.seed("notes.txt", "not markdown")
        self.pad.write("real", "")
        self.assertEqual(self.pad.list_keys(), ["real"])

    def test_list_keys_follows_pagination(self):
        """If Drive paginates the response, we should follow it."""
        # Seed two fake pages worth
        self.fake.seed("a.md", "")
        self.fake.seed("b.md", "")

        # Monkeypatch fake._list to simulate a pageToken on the first call
        original_list = self.fake._list
        pages = [
            {"files": [{"id": "id-1", "name": "a.md"}], "nextPageToken": "p2"},
            {"files": [{"id": "id-2", "name": "b.md"}]},
        ]

        def paged_list(**kwargs: Any) -> Any:
            self.fake.list_calls += 1
            resp = MagicMock()
            if kwargs.get("pageToken") == "p2":
                resp.execute.return_value = pages[1]
            else:
                resp.execute.return_value = pages[0]
            return resp

        service = MagicMock()
        svc_files = MagicMock()
        svc_files.list.side_effect = paged_list
        service.files.return_value = svc_files
        self.pad._service = service

        self.assertEqual(self.pad.list_keys(), ["a", "b"])
        # Two pages → two list() calls
        self.assertEqual(self.fake.list_calls, 2)
        # Restore so any teardown that reads state doesn't explode
        self.fake._list = original_list  # type: ignore[method-assign]


class TestDelete(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.pad = _make_pad(self.fake)

    def test_delete_removes_file(self):
        self.pad.write("k", "v")
        self.pad.delete("k")
        self.assertEqual(self.pad.list_keys(), [])
        self.assertEqual(self.fake.delete_calls, 1)

    def test_delete_unknown_is_noop(self):
        self.pad.delete("never-existed")
        self.assertEqual(self.fake.delete_calls, 0)


# ---------------------------------------------------------------------------
# Shared-drive flags
# ---------------------------------------------------------------------------


class TestSharedDriveFlags(unittest.TestCase):
    def test_list_passes_shared_drive_flags(self):
        fake = FakeDrive()
        pad = _make_pad(fake)

        pad.write("k", "v")
        pad.list_keys()
        pad.read("k")

        svc_files = pad._service.files.return_value
        for call in svc_files.list.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)
            self.assertIs(call.kwargs["includeItemsFromAllDrives"], True)


if __name__ == "__main__":
    unittest.main()
