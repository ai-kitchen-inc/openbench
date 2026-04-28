"""Tests for :class:`GoogleDriveMemoryStore`.

Exercises the v1 Phase 2 implementation against a fully in-memory
fake of the Drive API so the ``[gdrive]`` extras don't have to be
installed for unit tests. Inherits :class:`MemoryStoreContract` to
validate ABC conformance — same bar SQLite already passes.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from openbench.integrations.gdrive._etag_cache import _EtagCache
from openbench.integrations.gdrive.memory_store import GoogleDriveMemoryStore
from openbench.intelligence.base import Message, MessageRole
from openbench.testing.memory_store_contract import MemoryStoreContract

# ---------------------------------------------------------------------------
# FakeMemoryDrive — minimal googleapiclient stand-in
# ---------------------------------------------------------------------------


class FakeMemoryDrive:
    """In-memory Drive fake supporting folders + JSON files.

    Parses a small subset of the Drive ``q=`` query language used by
    :class:`GoogleDriveMemoryStore` — ``'<parent>' in parents``,
    ``name = '<value>'``, and ``mimeType = '<value>'`` clauses combined
    by ``and``. ``trashed = false`` is a no-op (nothing is ever
    trashed in the fake).
    """

    def __init__(self):
        # file_id -> metadata
        self.files_by_id: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        # Operation counters — useful for asserting round-trip count
        self.create_calls = 0
        self.update_calls = 0
        self.list_calls = 0
        self.delete_calls = 0
        self.get_media_calls = 0

    # ---- gapi surface -------------------------------------------------------

    def files(self) -> MagicMock:
        svc = MagicMock()
        svc.list.side_effect = self._list
        svc.get_media.side_effect = self._get_media
        svc.create.side_effect = self._create
        svc.update.side_effect = self._update
        svc.delete.side_effect = self._delete
        return svc

    # ---- helpers ------------------------------------------------------------

    def _mint_id(self) -> str:
        fid = f"id-{self._next_id}"
        self._next_id += 1
        return fid

    @staticmethod
    def _parse_q(q: str) -> dict[str, str]:
        """Pull out the simple ``key = '...'`` and ``in parents`` clauses."""
        clauses: dict[str, str] = {}
        m = re.search(r"'([^']+)'\s+in\s+parents", q)
        if m:
            clauses["parent"] = m.group(1)
        m = re.search(r"\bname\s*=\s*'([^']+)'", q)
        if m:
            clauses["name"] = m.group(1)
        m = re.search(r"\bmimeType\s*=\s*'([^']+)'", q)
        if m:
            clauses["mimeType"] = m.group(1)
        return clauses

    @staticmethod
    def _matches(meta: dict[str, Any], filters: dict[str, str]) -> bool:
        return all(
            [
                "parent" not in filters or filters["parent"] in (meta.get("parents") or []),
                "name" not in filters or meta.get("name") == filters["name"],
                "mimeType" not in filters or meta.get("mimeType") == filters["mimeType"],
            ]
        )

    # ---- gapi method side-effects ------------------------------------------

    def _list(self, **kwargs: Any) -> Any:
        self.list_calls += 1
        q = kwargs.get("q") or ""
        filters = self._parse_q(q)
        matched = [
            (fid, meta) for fid, meta in self.files_by_id.items() if self._matches(meta, filters)
        ]
        files = [{"id": fid, "name": meta["name"]} for fid, meta in matched]
        execute = MagicMock()
        execute.execute.return_value = {"files": files}
        return execute

    def _create(self, **kwargs: Any) -> Any:
        self.create_calls += 1
        body = kwargs.get("body") or {}
        media_body = kwargs.get("media_body")
        fid = self._mint_id()
        # ``media_body`` is a googleapiclient-style upload object, but
        # in our fake we accept any object with a ``getbytes`` /
        # ``data`` attribute, falling back to None for folder creation.
        content = b""
        if media_body is not None:
            content = self._extract_media_bytes(media_body)
        self.files_by_id[fid] = {
            "name": body.get("name"),
            "parents": list(body.get("parents") or []),
            "mimeType": body.get("mimeType"),
            "content": content,
        }
        execute = MagicMock()
        execute.execute.return_value = {"id": fid}
        return execute

    def _update(self, **kwargs: Any) -> Any:
        self.update_calls += 1
        fid = kwargs.get("fileId")
        media_body = kwargs.get("media_body")
        if fid in self.files_by_id and media_body is not None:
            self.files_by_id[fid]["content"] = self._extract_media_bytes(media_body)
        execute = MagicMock()
        execute.execute.return_value = {"id": fid}
        return execute

    def _delete(self, **kwargs: Any) -> Any:
        self.delete_calls += 1
        fid = kwargs.get("fileId")
        self.files_by_id.pop(fid, None)
        execute = MagicMock()
        execute.execute.return_value = ""
        return execute

    def _get_media(self, **kwargs: Any) -> Any:
        self.get_media_calls += 1
        fid = kwargs.get("fileId")
        meta = self.files_by_id.get(fid)
        execute = MagicMock()
        execute.execute.return_value = (meta or {}).get("content") or b""
        return execute

    @staticmethod
    def _extract_media_bytes(media_body: Any) -> bytes:
        """Pull bytes out of a real ``MediaInMemoryUpload`` or compatible."""
        # Real googleapiclient MediaInMemoryUpload exposes ``_body``.
        body = getattr(media_body, "_body", None)
        if isinstance(body, bytes):
            return body
        # Fallback to ``getbytes(0, -1)`` — the ``MediaIoBaseUpload`` API.
        getbytes = getattr(media_body, "getbytes", None)
        if callable(getbytes):
            try:
                return getbytes(0, -1) or b""
            except TypeError:
                pass
        # Last resort: whatever attribute holds bytes.
        for attr in ("data", "content", "body"):
            val = getattr(media_body, attr, None)
            if isinstance(val, bytes):
                return val
        return b""


# ---------------------------------------------------------------------------
# Contract suite — runs the full inherited test set against the Drive impl
# ---------------------------------------------------------------------------


class TestGoogleDriveMemoryStoreContract(MemoryStoreContract):
    """Run :class:`MemoryStoreContract` against :class:`GoogleDriveMemoryStore`."""

    def make_store(self) -> GoogleDriveMemoryStore:
        fake = FakeMemoryDrive()
        store = GoogleDriveMemoryStore(
            folder_id="root-folder",
            credentials=MagicMock(),  # bypass auth path
        )
        # Inject the fake directly via the lazy ``_service`` slot so
        # ``_build_service`` is never called (which would import gapi).
        store._service = fake
        # Stash the fake on the store so individual tests can introspect
        # call counts when needed (see Drive-specific tests below).
        store._fake = fake  # type: ignore[attr-defined]
        return store


# ---------------------------------------------------------------------------
# Drive-specific behavioral tests (beyond the ABC contract)
# ---------------------------------------------------------------------------


def _new_store() -> tuple[GoogleDriveMemoryStore, FakeMemoryDrive]:
    fake = FakeMemoryDrive()
    store = GoogleDriveMemoryStore(folder_id="root-folder", credentials=MagicMock())
    store._service = fake
    return store, fake


def test_subfolder_created_lazily_on_first_save():
    """The ``memory/`` subfolder is created on the first write, not on load."""
    store, fake = _new_store()
    # Pre-write: load against an empty backend should NOT create the subfolder.
    assert store.load("nope") == []
    folder_count = sum(
        1 for m in fake.files_by_id.values() if m.get("mimeType", "").endswith("folder")
    )
    assert folder_count == 0

    # First write creates the folder + the blob.
    from openbench.intelligence.base import Message, MessageRole

    store.save("s1", [Message(role=MessageRole.USER, content="hi")])
    folders = [m for m in fake.files_by_id.values() if m.get("mimeType", "").endswith("folder")]
    blobs = [m for m in fake.files_by_id.values() if m.get("mimeType") == "application/json"]
    assert len(folders) == 1
    assert folders[0]["name"] == "memory"
    assert len(blobs) == 1
    assert blobs[0]["name"] == "s1.json"


def test_save_then_save_updates_existing_blob_in_place():
    """Two saves to the same session_id update the same blob, not create a new one."""
    store, fake = _new_store()
    from openbench.intelligence.base import Message, MessageRole

    store.save("s1", [Message(role=MessageRole.USER, content="one")])
    store.save("s1", [Message(role=MessageRole.USER, content="two")])

    blob_files = [m for m in fake.files_by_id.values() if m.get("mimeType") == "application/json"]
    assert len(blob_files) == 1
    # Update calls should fire after the first save's create.
    assert fake.update_calls >= 1


def test_search_returns_empty_and_does_not_query_drive():
    store, fake = _new_store()
    pre = fake.list_calls
    assert store.search("anything") == []
    # ``search`` shouldn't even hit Drive — pure no-op.
    assert fake.list_calls == pre


def test_corrupt_blob_returns_empty_list_no_raise():
    """If the blob has invalid JSON, load surfaces ``[]`` and logs."""
    store, fake = _new_store()
    # Manually plant a corrupt blob inside a memory/ subfolder.
    folder_id = "fake-folder"
    fake.files_by_id[folder_id] = {
        "name": "memory",
        "parents": ["root-folder"],
        "mimeType": "application/vnd.google-apps.folder",
        "content": b"",
    }
    fake.files_by_id["fake-blob"] = {
        "name": "broken.json",
        "parents": [folder_id],
        "mimeType": "application/json",
        "content": b"this is not JSON {",
    }
    assert store.load("broken") == []


def test_subfolder_name_is_configurable():
    """Custom subfolder_name is honored on lookup + creation."""
    fake = FakeMemoryDrive()
    store = GoogleDriveMemoryStore(
        folder_id="root-folder",
        credentials=MagicMock(),
        subfolder_name="agent-memory",
    )
    store._service = fake
    from openbench.intelligence.base import Message, MessageRole

    store.save("s1", [Message(role=MessageRole.USER, content="hi")])
    folder = next(m for m in fake.files_by_id.values() if m.get("mimeType", "").endswith("folder"))
    assert folder["name"] == "agent-memory"


def test_constructor_rejects_missing_credentials_and_account():
    with pytest.raises(ValueError, match="service_account_file"):
        GoogleDriveMemoryStore(folder_id="x")


def test_constructor_rejects_empty_folder_id():
    with pytest.raises(ValueError, match="folder_id"):
        GoogleDriveMemoryStore(folder_id="", credentials=MagicMock())


def test_constructor_rejects_empty_subfolder_name():
    with pytest.raises(ValueError, match="subfolder_name"):
        GoogleDriveMemoryStore(
            folder_id="root",
            credentials=MagicMock(),
            subfolder_name="",
        )


def test_repr_includes_folder_and_subfolder():
    store = GoogleDriveMemoryStore(
        folder_id="abc",
        credentials=MagicMock(),
        subfolder_name="custom",
    )
    text = repr(store)
    assert "abc" in text
    assert "custom" in text


def test_build_service_raises_when_gapi_missing():
    """Without ``[gdrive]`` extras, building the service raises ImportError."""
    store = GoogleDriveMemoryStore(folder_id="x", credentials=MagicMock())
    # Force the lazy build path by clearing the cached service.
    store._service = None
    with (
        patch.dict(
            "sys.modules",
            {"googleapiclient.discovery": None},
        ),
        pytest.raises(ImportError, match="gdrive"),
    ):
        store._build_service()


# ---------------------------------------------------------------------------
# Read cache integration — load/save/delete interaction with _EtagCache
# ---------------------------------------------------------------------------


def test_load_hits_cache_and_skips_drive_on_repeat():
    """Two loads of the same session id round-trip Drive once."""
    store, fake = _new_store()
    store.save("s1", [Message(role=MessageRole.USER, content="hi")])
    # Save calls list (find blob) + create. Reset counters to isolate
    # the load behavior.
    fake.list_calls = 0
    fake.get_media_calls = 0

    first = store.load("s1")
    after_first_list = fake.list_calls
    after_first_media = fake.get_media_calls
    second = store.load("s1")

    assert [m.content for m in first] == ["hi"]
    assert [m.content for m in second] == ["hi"]
    # Second load is a pure cache hit — no Drive calls.
    assert fake.list_calls == after_first_list
    assert fake.get_media_calls == after_first_media


def test_save_warms_cache_so_next_load_skips_drive():
    """``save`` populates the cache directly with the merged history."""
    store, fake = _new_store()
    store.save("s1", [Message(role=MessageRole.USER, content="hi")])
    fake.list_calls = 0
    fake.get_media_calls = 0

    loaded = store.load("s1")
    assert [m.content for m in loaded] == ["hi"]
    assert fake.list_calls == 0
    assert fake.get_media_calls == 0


def test_delete_session_invalidates_cache_entry():
    """After delete, load returns ``[]`` even if the cache had warmth."""
    store, _fake = _new_store()
    store.save("s1", [Message(role=MessageRole.USER, content="hi")])
    # Confirm cache is warm.
    assert "s1" in store._cache  # type: ignore[operator]

    store.delete_session("s1")
    assert "s1" not in store._cache  # type: ignore[operator]
    assert store.load("s1") == []


def test_enable_cache_false_disables_caching():
    """When ``enable_cache=False``, every load round-trips Drive."""
    fake = FakeMemoryDrive()
    store = GoogleDriveMemoryStore(
        folder_id="root-folder",
        credentials=MagicMock(),
        enable_cache=False,
    )
    store._service = fake
    store.save("s1", [Message(role=MessageRole.USER, content="hi")])
    fake.list_calls = 0
    fake.get_media_calls = 0

    store.load("s1")
    store.load("s1")

    assert store._cache is None
    assert fake.list_calls > 0
    assert fake.get_media_calls > 0


def test_load_after_ttl_expiry_falls_through_to_drive():
    """An entry past its TTL is dropped on access and refetched."""
    fake = FakeMemoryDrive()
    store = GoogleDriveMemoryStore(
        folder_id="root-folder",
        credentials=MagicMock(),
        cache_ttl_seconds=10.0,
    )
    store._service = fake
    store.save("s1", [Message(role=MessageRole.USER, content="hi")])

    # Fast-forward time past the TTL by patching ``time.monotonic``
    # inside the cache module.
    fake.list_calls = 0
    fake.get_media_calls = 0
    with patch(
        "openbench.integrations.gdrive._etag_cache.time.monotonic",
        return_value=1e9,  # arbitrary far-future timestamp
    ):
        store.load("s1")
    # Cache miss → Drive round-trip happened.
    assert fake.list_calls > 0 or fake.get_media_calls > 0


def test_cache_constructor_params_are_validated():
    """Invalid cache settings surface as ValueError at __init__."""
    with pytest.raises(ValueError, match="ttl_seconds"):
        GoogleDriveMemoryStore(
            folder_id="x",
            credentials=MagicMock(),
            cache_ttl_seconds=0,
        )
    with pytest.raises(ValueError, match="max_sessions"):
        GoogleDriveMemoryStore(
            folder_id="x",
            credentials=MagicMock(),
            cache_max_sessions=0,
        )


# ---------------------------------------------------------------------------
# _EtagCache unit tests — pure data-structure behavior
# ---------------------------------------------------------------------------


def _stub_messages(*contents: str) -> list[Message]:
    return [Message(role=MessageRole.USER, content=c) for c in contents]


def test_etag_cache_get_returns_none_on_miss():
    cache = _EtagCache()
    assert cache.get("never-saved") is None


def test_etag_cache_put_then_get_returns_copy():
    cache = _EtagCache()
    original = _stub_messages("a", "b")
    cache.put("s1", original)
    fetched = cache.get("s1")
    assert fetched == original
    # Mutating the fetched list must not corrupt the cache.
    assert fetched is not None
    fetched.append(Message(role=MessageRole.USER, content="oops"))
    again = cache.get("s1")
    assert again is not None
    assert [m.content for m in again] == ["a", "b"]


def test_etag_cache_get_after_ttl_returns_none_and_drops_entry():
    cache = _EtagCache(ttl_seconds=10.0)
    cache.put("s1", _stub_messages("a"))
    with patch(
        "openbench.integrations.gdrive._etag_cache.time.monotonic",
        return_value=1e9,
    ):
        assert cache.get("s1") is None
    assert "s1" not in cache


def test_etag_cache_put_resets_ttl_clock():
    cache = _EtagCache(ttl_seconds=10.0)
    with patch(
        "openbench.integrations.gdrive._etag_cache.time.monotonic",
        return_value=0.0,
    ):
        cache.put("s1", _stub_messages("a"))
    with patch(
        "openbench.integrations.gdrive._etag_cache.time.monotonic",
        return_value=15.0,
    ):
        # Re-put refreshes the entry → still fresh at t=15+5
        cache.put("s1", _stub_messages("a", "b"))
    with patch(
        "openbench.integrations.gdrive._etag_cache.time.monotonic",
        return_value=20.0,
    ):
        fetched = cache.get("s1")
    assert fetched is not None
    assert [m.content for m in fetched] == ["a", "b"]


def test_etag_cache_invalidate_drops_single_entry():
    cache = _EtagCache()
    cache.put("s1", _stub_messages("a"))
    cache.put("s2", _stub_messages("b"))
    cache.invalidate("s1")
    assert "s1" not in cache
    assert "s2" in cache


def test_etag_cache_invalidate_unknown_is_noop():
    cache = _EtagCache()
    cache.invalidate("nope")  # must not raise


def test_etag_cache_clear_drops_all_entries():
    cache = _EtagCache()
    cache.put("s1", _stub_messages("a"))
    cache.put("s2", _stub_messages("b"))
    cache.clear()
    assert len(cache) == 0


def test_etag_cache_lru_evicts_oldest_at_max():
    cache = _EtagCache(max_sessions=2)
    cache.put("s1", _stub_messages("a"))
    cache.put("s2", _stub_messages("b"))
    cache.put("s3", _stub_messages("c"))  # evicts s1
    assert "s1" not in cache
    assert "s2" in cache
    assert "s3" in cache


def test_etag_cache_get_marks_entry_most_recently_used():
    cache = _EtagCache(max_sessions=2)
    cache.put("s1", _stub_messages("a"))
    cache.put("s2", _stub_messages("b"))
    # Touch s1 — now s2 is least recently used.
    cache.get("s1")
    cache.put("s3", _stub_messages("c"))  # should evict s2, not s1
    assert "s1" in cache
    assert "s2" not in cache
    assert "s3" in cache


def test_etag_cache_constructor_rejects_zero_or_negative():
    with pytest.raises(ValueError, match="max_sessions"):
        _EtagCache(max_sessions=0)
    with pytest.raises(ValueError, match="ttl_seconds"):
        _EtagCache(ttl_seconds=0)


def test_etag_cache_contains_only_returns_true_for_strings():
    cache = _EtagCache()
    cache.put("s1", _stub_messages("a"))
    assert "s1" in cache
    assert 123 not in cache  # non-string key
    assert object() not in cache
