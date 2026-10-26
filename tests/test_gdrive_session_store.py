"""Tests for :class:`GoogleDriveSessionStore`.

Mocks the Drive API with an in-memory fake that tracks file bodies
**and** appProperties so list/load/save/delete round-trip correctly
without needing the ``[gdrive]`` extras installed.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.chat.session import Attachment, ChatSession
from openbench.chat.session_store import SessionSummary
from openbench.integrations.gdrive import GoogleDriveSessionStore

# ---------------------------------------------------------------------------
# FakeDrive — tiny in-memory gapi stand-in that supports appProperties
# ---------------------------------------------------------------------------


class FakeDrive:
    def __init__(self, folder_id: str = "sessions-folder"):
        self.folder_id = folder_id
        # file_id -> {"name", "content" (bytes), "appProperties", "modifiedOrder"}
        self.files_by_id: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self._modified_counter = 0
        self.list_calls = 0
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0
        self.get_media_calls = 0

    # ---- public test helpers ------------------------------------------------

    def file_by_name(self, name: str) -> dict[str, Any] | None:
        for meta in self.files_by_id.values():
            if meta["name"] == name:
                return meta
        return None

    def names(self) -> list[str]:
        return sorted(meta["name"] for meta in self.files_by_id.values())

    # ---- gapi surface -------------------------------------------------------

    def files(self) -> MagicMock:
        svc = MagicMock()
        svc.list.side_effect = self._list
        svc.get_media.side_effect = self._get_media
        svc.create.side_effect = self._create
        svc.update.side_effect = self._update
        svc.delete.side_effect = self._delete
        return svc

    def _mint_id(self) -> str:
        fid = f"id-{self._next_id}"
        self._next_id += 1
        return fid

    def _bump_modified(self) -> int:
        self._modified_counter += 1
        return self._modified_counter

    def _list(self, **kwargs: Any) -> Any:
        self.list_calls += 1
        q = kwargs.get("q", "")
        order_by = kwargs.get("orderBy", "")

        name_match = re.search(r"name = '([^']+)'", q)
        if name_match is not None:
            needle = name_match.group(1)
            matches_items = [
                (fid, meta) for fid, meta in self.files_by_id.items() if meta["name"] == needle
            ]
        else:
            # No name filter — list every json file in folder.
            matches_items = [
                (fid, meta)
                for fid, meta in self.files_by_id.items()
                if meta["name"].endswith(".json")
            ]

        if "modifiedTime desc" in order_by:
            matches_items.sort(key=lambda pair: pair[1]["modifiedOrder"], reverse=True)

        files_out = [
            {
                "id": fid,
                "name": meta["name"],
                "appProperties": dict(meta.get("appProperties") or {}),
            }
            for fid, meta in matches_items
        ]
        resp = MagicMock()
        resp.execute.return_value = {"files": files_out}
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
            "appProperties": dict(body.get("appProperties") or {}),
            "modifiedOrder": self._bump_modified(),
        }
        resp = MagicMock()
        resp.execute.return_value = {"id": fid}
        return resp

    def _update(
        self, fileId: str, body: dict[str, Any] | None = None, media_body: Any = None, **_: Any
    ) -> Any:
        self.update_calls += 1
        if fileId in self.files_by_id:
            meta = self.files_by_id[fileId]
            if media_body is not None:
                meta["content"] = media_body.body_bytes
            if body is not None and "appProperties" in body:
                # Merge semantics: Drive overwrites specified keys and
                # leaves others alone. Our impl sends the full dict so
                # this is equivalent to replace.
                meta["appProperties"] = dict(body["appProperties"] or {})
            meta["modifiedOrder"] = self._bump_modified()
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
    def __init__(self, body: bytes, mimetype: str = "application/json"):
        self.body_bytes = body
        self.mimetype = mimetype


def _make_store(fake: FakeDrive) -> GoogleDriveSessionStore:
    store = GoogleDriveSessionStore(
        folder_id=fake.folder_id,
        service_account_file="/fake/creds.json",
    )
    service = MagicMock()
    service.files.side_effect = fake.files
    store._service = service
    store._media = lambda data_json: FakeMedia(data_json.encode("utf-8"))  # type: ignore[method-assign]
    return store


def _make_session(session_id: str = "s-1", title: str = "Demo") -> ChatSession:
    session = ChatSession(session_id=session_id, title=title)
    session.add_user_message("hello world")
    session.add_assistant_message(content="hi back", surfaces=[{"surfaceId": "s1"}])
    return session


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_requires_folder_id(self):
        with self.assertRaises(ValueError):
            GoogleDriveSessionStore(folder_id="", service_account_file="/x")

    def test_requires_auth(self):
        with self.assertRaises(ValueError):
            GoogleDriveSessionStore(folder_id="f")

    def test_accepts_service_account_file(self):
        s = GoogleDriveSessionStore(folder_id="f", service_account_file="/x")
        self.assertEqual(s.folder_id, "f")

    def test_accepts_explicit_credentials(self):
        s = GoogleDriveSessionStore(folder_id="f", credentials=object())
        self.assertEqual(s.folder_id, "f")

    def test_construction_is_offline(self):
        GoogleDriveSessionStore(folder_id="f", service_account_file="/x")

    def test_repr_includes_folder(self):
        s = GoogleDriveSessionStore(folder_id="xyz", service_account_file="/x")
        self.assertIn("xyz", repr(s))


class TestMissingDependency(unittest.TestCase):
    def test_lazy_build_raises_import_error(self):
        s = GoogleDriveSessionStore(folder_id="f", service_account_file="/x")
        with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
            with self.assertRaises(ImportError) as ctx:
                s._build_service()
            self.assertIn("pip install openbench[gdrive]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------


class TestSaveLoad(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.store = _make_store(self.fake)

    def test_save_creates_new_file(self):
        self.store.save(_make_session("s-1", "First"))
        self.assertEqual(self.fake.names(), ["s-1.json"])
        self.assertEqual(self.fake.create_calls, 1)

    def test_save_writes_json_body(self):
        self.store.save(_make_session("s-1"))
        meta = self.fake.file_by_name("s-1.json")
        assert meta is not None
        parsed = json.loads(meta["content"].decode("utf-8"))
        self.assertEqual(parsed["sessionId"], "s-1")
        self.assertEqual(len(parsed["messages"]), 2)

    def test_save_stamps_app_properties(self):
        session = _make_session("s-1", title="Q1 Review")
        self.store.save(session)
        meta = self.fake.file_by_name("s-1.json")
        assert meta is not None
        props = meta["appProperties"]
        self.assertEqual(props["ob_title"], "Q1 Review")
        self.assertEqual(props["ob_msg_count"], "2")
        self.assertEqual(props["ob_preview"], "hello world")
        self.assertIn(":", props["ob_created_at"])  # ISO 8601

    def test_save_is_idempotent_and_updates_existing(self):
        session = _make_session("s-1", title="v1")
        self.store.save(session)

        session.title = "v2"
        session.add_user_message("another")
        self.store.save(session)

        self.assertEqual(self.fake.create_calls, 1)
        self.assertEqual(self.fake.update_calls, 1)
        reloaded = self.store.load("s-1")
        assert reloaded is not None
        self.assertEqual(reloaded.title, "v2")
        self.assertEqual(len(reloaded.messages), 3)

    def test_load_returns_none_for_unknown_id(self):
        self.assertIsNone(self.store.load("nope"))

    def test_load_roundtrip_preserves_attachments(self):
        attachment = Attachment(
            id="att-1",
            type="file",
            name="doc.pdf",
            url="https://example.com/doc.pdf",
            mime_type="application/pdf",
            size_bytes=256,
        )
        session = ChatSession(session_id="s-att", title="Attached")
        session.add_user_message("see", attachments=[attachment])
        self.store.save(session)

        reloaded = self.store.load("s-att")
        assert reloaded is not None
        self.assertEqual(len(reloaded.messages[0].attachments or []), 1)
        self.assertEqual(reloaded.messages[0].attachments[0].name, "doc.pdf")

    def test_load_skips_corrupt_session_file(self):
        """Corrupted JSON should not blow up load()."""
        # Simulate a corrupt file by poking bytes directly into FakeDrive
        self.fake.files_by_id["id-corrupt"] = {
            "name": "s-bad.json",
            "content": b"NOT VALID JSON",
            "appProperties": {},
            "modifiedOrder": 1,
        }
        self.assertIsNone(self.store.load("s-bad"))

    def test_preview_truncates_long_first_user_message(self):
        session = ChatSession(session_id="s-long", title="Long")
        session.add_user_message("x" * 500)
        self.store.save(session)
        meta = self.fake.file_by_name("s-long.json")
        assert meta is not None
        preview = meta["appProperties"]["ob_preview"]
        self.assertTrue(preview.endswith("\u2026"))
        self.assertEqual(len(preview), 100)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.store = _make_store(self.fake)

    def test_empty_folder_returns_empty(self):
        self.assertEqual(self.store.list(), [])

    def test_list_orders_newest_first(self):
        self.store.save(_make_session("s-1", "Oldest"))
        self.store.save(_make_session("s-2", "Middle"))
        self.store.save(_make_session("s-3", "Newest"))

        summaries = self.store.list()
        self.assertEqual([s.session_id for s in summaries], ["s-3", "s-2", "s-1"])

    def test_list_respects_limit(self):
        for i in range(5):
            self.store.save(_make_session(f"s-{i}", f"S{i}"))
        result = self.store.list(limit=2)
        self.assertEqual(len(result), 2)

    def test_list_respects_offset(self):
        for i in range(4):
            self.store.save(_make_session(f"s-{i}", f"S{i}"))
        # Newest first: s-3, s-2, s-1, s-0
        result = self.store.list(limit=2, offset=1)
        self.assertEqual([s.session_id for s in result], ["s-2", "s-1"])

    def test_list_zero_limit_returns_empty(self):
        self.store.save(_make_session("s-1"))
        self.assertEqual(self.store.list(limit=0), [])

    def test_list_returns_summary_instances(self):
        self.store.save(_make_session("s-1", "Demo"))
        summaries = self.store.list()
        self.assertEqual(len(summaries), 1)
        self.assertIsInstance(summaries[0], SessionSummary)
        self.assertEqual(summaries[0].title, "Demo")
        self.assertEqual(summaries[0].message_count, 2)
        self.assertEqual(summaries[0].preview, "hello world")

    def test_list_skips_files_with_missing_app_properties(self):
        """Files without the required timestamps are filtered out quietly."""
        self.store.save(_make_session("s-good", "Good"))
        # Inject a naked json file with no appProperties
        self.fake.files_by_id["id-naked"] = {
            "name": "s-naked.json",
            "content": b"{}",
            "appProperties": {},
            "modifiedOrder": 999,
        }
        summaries = self.store.list()
        ids = [s.session_id for s in summaries]
        self.assertEqual(ids, ["s-good"])


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrive()
        self.store = _make_store(self.fake)

    def test_delete_removes_session(self):
        self.store.save(_make_session("s-1"))
        self.store.delete("s-1")
        self.assertIsNone(self.store.load("s-1"))
        self.assertEqual(self.fake.delete_calls, 1)

    def test_delete_unknown_is_noop(self):
        self.store.delete("never-existed")
        self.assertEqual(self.fake.delete_calls, 0)


# ---------------------------------------------------------------------------
# Shared-drive flags
# ---------------------------------------------------------------------------


class TestSharedDriveFlags(unittest.TestCase):
    def test_list_and_create_pass_shared_drive_flags(self):
        fake = FakeDrive()
        store = _make_store(fake)
        store.save(_make_session("s-1"))
        store.list()
        store.delete("s-1")

        svc_files = store._service.files.return_value
        for call in svc_files.list.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)
            self.assertIs(call.kwargs["includeItemsFromAllDrives"], True)
        for call in svc_files.create.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)
        for call in svc_files.delete.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)


if __name__ == "__main__":
    unittest.main()
