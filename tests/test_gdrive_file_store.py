"""Tests for :class:`GoogleDriveFileStore` — chat upload store on Drive.

FakeDrive records every create/update/get_media so we can assert
upload happened, cache was populated, and download-on-demand honored
the TTL. No network, no google-api-python-client reach.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


class FakeDrive:
    """Minimal Drive model: one folder with files keyed by Drive file id."""

    def __init__(self):
        self._files: dict[str, dict] = {}  # file_id -> {name, content, mime, app_props}
        self._next = 1

    def _mint(self) -> str:
        self._next += 1
        return f"drive-{self._next}"

    def build_service(self):
        svc = MagicMock()

        def _create(**kwargs):
            body = kwargs["body"]
            fid = self._mint()
            media = kwargs.get("media_body")
            content = b""
            if media is not None:
                fd = getattr(media, "_fd", None)
                if fd is not None:
                    content = fd.getvalue()
                else:
                    content = getattr(media, "_body", b"") or b""
            view_link = f"https://drive.google.com/file/d/{fid}/view"
            self._files[fid] = {
                "id": fid,
                "name": body["name"],
                "mimeType": body.get("mimeType", "application/octet-stream"),
                "content": content,
                "appProperties": body.get("appProperties") or {},
                "size": len(content),
                "modifiedTime": "2026-04-18T00:00:00Z",
                "webViewLink": view_link,
            }
            # Honour ``fields`` — return only what the caller asked for.
            fields = kwargs.get("fields", "id")
            resp: dict[str, Any] = {"id": fid}
            if "webViewLink" in fields:
                resp["webViewLink"] = view_link
            return MagicMock(execute=MagicMock(return_value=resp))

        def _get(**kwargs):
            fid = kwargs["fileId"]
            rec = self._files.get(fid)
            if rec is None:
                raise RuntimeError(f"not found: {fid}")
            return MagicMock(
                execute=MagicMock(
                    return_value={
                        "id": rec["id"],
                        "name": rec["name"],
                        "mimeType": rec["mimeType"],
                        "size": str(rec["size"]),
                        "modifiedTime": rec["modifiedTime"],
                        "appProperties": rec["appProperties"],
                        "webViewLink": rec["webViewLink"],
                    }
                )
            )

        def _get_media(**kwargs):
            fid = kwargs["fileId"]
            rec = self._files.get(fid)
            if rec is None:
                raise RuntimeError(f"not found: {fid}")
            return MagicMock(execute=MagicMock(return_value=rec["content"]))

        files = MagicMock()
        files.create = MagicMock(side_effect=_create)
        files.get = MagicMock(side_effect=_get)
        files.get_media = MagicMock(side_effect=_get_media)
        svc.files = MagicMock(return_value=files)
        return svc


class TestGoogleDriveFileStore(unittest.TestCase):
    def setUp(self):
        from openbench.integrations.gdrive import GoogleDriveFileStore

        self.drive = FakeDrive()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = GoogleDriveFileStore(
            folder_id="uploads-folder",
            cache_root=self._tmp.name,
            credentials=object(),  # required; content ignored because we patch _build_service
        )
        # Swap in the fake service.
        self.store._service = self.drive.build_service()

    def test_construction_rejects_empty_folder(self):
        from openbench.integrations.gdrive import GoogleDriveFileStore

        with self.assertRaises(ValueError):
            GoogleDriveFileStore(folder_id="", cache_root=self._tmp.name, credentials=object())

    def test_construction_requires_auth(self):
        from openbench.integrations.gdrive import GoogleDriveFileStore

        with self.assertRaises(ValueError):
            GoogleDriveFileStore(folder_id="f", cache_root=self._tmp.name)

    def test_store_uploads_and_returns_drive_id(self):
        stored = self.store.store("data.xlsx", b"binary-content", "application/vnd.ms-excel")
        self.assertTrue(stored.id.startswith("drive-"))
        self.assertEqual(stored.name, "data.xlsx")
        self.assertEqual(stored.mime_type, "application/vnd.ms-excel")
        # Cache populated so a subsequent get_local_path is free.
        self.assertTrue(Path(stored.path).exists())
        self.assertEqual(Path(stored.path).read_bytes(), b"binary-content")

    def test_store_sanitises_unsafe_filename(self):
        stored = self.store.store("../../etc/passwd", b"x", "text/plain")
        self.assertEqual(stored.name, "passwd")
        self.assertTrue(Path(stored.path).exists())

    def test_get_local_path_uses_cache_when_fresh(self):
        stored = self.store.store("report.md", b"hello", "text/markdown")
        # Reset the get_media call count so we can assert it's NOT called.
        get_media = self.store._service.files.return_value.get_media
        get_media.reset_mock()
        path = self.store.get_local_path(stored.id)
        self.assertEqual(path, stored.path)
        # get_media hit zero times — served from cache.
        self.assertEqual(get_media.call_count, 0)

    def test_get_local_path_downloads_when_cache_missing(self):
        stored = self.store.store("report.md", b"hello", "text/markdown")
        # Wipe the cache directory.
        Path(stored.path).unlink()
        get_media = self.store._service.files.return_value.get_media
        get_media.reset_mock()
        path = self.store.get_local_path(stored.id)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(Path(path).read_bytes(), b"hello")
        self.assertEqual(get_media.call_count, 1)

    def test_get_local_path_redownloads_when_cache_stale(self):
        from openbench.integrations.gdrive.file_store import CACHE_TTL_SECONDS

        stored = self.store.store("report.md", b"hello", "text/markdown")
        # Age the cached file past the TTL.
        stale = time.time() - (CACHE_TTL_SECONDS + 60)
        import os as _os

        _os.utime(stored.path, (stale, stale))
        get_media = self.store._service.files.return_value.get_media
        get_media.reset_mock()
        path = self.store.get_local_path(stored.id)
        self.assertIsNotNone(path)
        self.assertEqual(get_media.call_count, 1)

    def test_get_missing_id_returns_none(self):
        self.assertIsNone(self.store.get("never-stored"))
        self.assertIsNone(self.store.get_local_path("never-stored"))

    def test_get_returns_metadata_without_downloading(self):
        stored = self.store.store("notes.md", b"body", "text/markdown")
        # The get() call should hit files.get() but NOT files.get_media().
        get_media = self.store._service.files.return_value.get_media
        get_media.reset_mock()
        meta = self.store.get(stored.id)
        assert meta is not None
        self.assertEqual(meta.id, stored.id)
        self.assertEqual(meta.name, "notes.md")
        self.assertEqual(meta.size_bytes, 4)
        self.assertEqual(get_media.call_count, 0)

    def test_conforms_to_file_store_protocol(self):
        from openbench.chat.files import FileStore

        self.assertIsInstance(self.store, FileStore)

    def test_store_populates_web_view_link_from_drive(self):
        """Drive returns a webViewLink on create — surface it so the frontend
        can open the file in the user's own Drive UI without proxying."""
        stored = self.store.store("spread.xlsx", b"xyz", "application/vnd.ms-excel")
        self.assertIsNotNone(stored.web_view_link)
        assert stored.web_view_link is not None
        self.assertTrue(stored.web_view_link.startswith("https://drive.google.com/file/"))

    def test_get_returns_web_view_link_from_metadata(self):
        """Re-reading an existing Drive file must also expose the viewer link."""
        created = self.store.store("r.xlsx", b"b", "application/vnd.ms-excel")
        meta = self.store.get(created.id)
        assert meta is not None
        self.assertIsNotNone(meta.web_view_link)
        self.assertEqual(meta.web_view_link, created.web_view_link)


class TestCacheGC(unittest.TestCase):
    def test_stale_entries_cleaned_opportunistically(self):
        from openbench.integrations.gdrive import GoogleDriveFileStore
        from openbench.integrations.gdrive.file_store import CACHE_TTL_SECONDS

        drive = FakeDrive()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        store = GoogleDriveFileStore(folder_id="f", cache_root=tmp.name, credentials=object())
        store._service = drive.build_service()

        # Write two files, then age one into staleness.
        a = store.store("a.md", b"A", "text/markdown")
        b = store.store("b.md", b"B", "text/markdown")

        stale = time.time() - (CACHE_TTL_SECONDS + 60)
        import os as _os

        _os.utime(a.path, (stale, stale))

        # Any subsequent call triggers _gc_cache inline.
        store.store("c.md", b"C", "text/markdown")

        # Stale a.md gone, fresh b.md remains.
        self.assertFalse(Path(a.path).exists())
        self.assertTrue(Path(b.path).exists())


if __name__ == "__main__":
    unittest.main()
