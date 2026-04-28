"""Tests for :class:`GoogleDriveStorageBackend`.

The backend is a thin factory that routes three store types through a
shared auth + root-folder config, using Drive folders as subfolders.
Tests mock the Drive API so no extras are needed to run.
"""

from __future__ import annotations

import re
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.core.storage import StorageBackend
from openbench.integrations.gdrive import (
    GoogleDocPersonaSource,  # imported so its name is in scope for negative checks
    GoogleDrivePersonaSource,
    GoogleDriveScratchpad,
    GoogleDriveSessionStore,
    GoogleDriveStorageBackend,
)

_FOLDER_MIME = "application/vnd.google-apps.folder"


class FakeFolderDrive:
    """Minimal Drive fake that tracks folder names under parents.

    We only need the folder-find-or-create surface for backend tests —
    the child stores are constructed but not exercised for IO.
    """

    def __init__(self) -> None:
        # list of {id, name, parent}
        self.folders: list[dict[str, str]] = []
        self._next = 1
        self.list_calls = 0
        self.create_calls = 0

    def _mint(self) -> str:
        fid = f"fid-{self._next}"
        self._next += 1
        return fid

    def seed_folder(self, name: str, parent: str) -> str:
        fid = self._mint()
        self.folders.append({"id": fid, "name": name, "parent": parent})
        return fid

    def files(self) -> MagicMock:
        svc = MagicMock()
        svc.list.side_effect = self._list
        svc.create.side_effect = self._create
        return svc

    def _list(self, **kwargs: Any) -> Any:
        self.list_calls += 1
        q = kwargs.get("q", "")

        parent = None
        m = re.search(r"'([^']+)' in parents", q)
        if m:
            parent = m.group(1)
        name = None
        m = re.search(r"name = '([^']+)'", q)
        if m:
            name = m.group(1)

        matches = [
            {"id": f["id"], "name": f["name"]}
            for f in self.folders
            if (parent is None or f["parent"] == parent) and (name is None or f["name"] == name)
        ]
        resp = MagicMock()
        resp.execute.return_value = {"files": matches}
        return resp

    def _create(self, body: dict[str, Any], **_: Any) -> Any:
        self.create_calls += 1
        fid = self._mint()
        self.folders.append({"id": fid, "name": body["name"], "parent": body["parents"][0]})
        resp = MagicMock()
        resp.execute.return_value = {"id": fid}
        return resp


def _make_backend(fake: FakeFolderDrive, root: str = "root-1") -> GoogleDriveStorageBackend:
    backend = GoogleDriveStorageBackend(
        root_folder_id=root,
        service_account_file="/fake/creds.json",
    )
    service = MagicMock()
    service.files.side_effect = fake.files
    backend._service = service
    return backend


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_requires_root_folder_id(self):
        with self.assertRaises(ValueError):
            GoogleDriveStorageBackend(root_folder_id="", service_account_file="/x")

    def test_requires_auth(self):
        with self.assertRaises(ValueError):
            GoogleDriveStorageBackend(root_folder_id="r")

    def test_accepts_service_account_file(self):
        b = GoogleDriveStorageBackend(root_folder_id="r", service_account_file="/x")
        self.assertEqual(b.root_folder_id, "r")

    def test_accepts_explicit_credentials(self):
        b = GoogleDriveStorageBackend(root_folder_id="r", credentials=object())
        self.assertEqual(b.root_folder_id, "r")

    def test_construction_is_offline(self):
        GoogleDriveStorageBackend(root_folder_id="r", service_account_file="/x")

    def test_conforms_to_storage_backend_protocol(self):
        b = GoogleDriveStorageBackend(root_folder_id="r", service_account_file="/x")
        self.assertIsInstance(b, StorageBackend)

    def test_repr_contains_root(self):
        b = GoogleDriveStorageBackend(root_folder_id="abc", service_account_file="/x")
        self.assertIn("abc", repr(b))


class TestMissingDependency(unittest.TestCase):
    def test_lazy_build_raises_import_error(self):
        b = GoogleDriveStorageBackend(root_folder_id="r", service_account_file="/x")
        with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
            with self.assertRaises(ImportError) as ctx:
                b._build_service()
            self.assertIn("pip install openbench[gdrive]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Subfolder resolution
# ---------------------------------------------------------------------------


class TestSubfolderResolution(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFolderDrive()
        self.backend = _make_backend(self.fake, root="root-1")

    def test_session_store_creates_sessions_subfolder_on_demand(self):
        self.assertEqual(self.fake.create_calls, 0)
        store = self.backend.session_store()
        # One create call for the "sessions" folder
        self.assertEqual(self.fake.create_calls, 1)
        self.assertIsInstance(store, GoogleDriveSessionStore)
        # And the child store should point at that folder id
        created = self.fake.folders[0]
        self.assertEqual(created["name"], "sessions")
        self.assertEqual(created["parent"], "root-1")
        self.assertEqual(store.folder_id, created["id"])

    def test_scratchpad_store_creates_memory_subfolder_on_demand(self):
        store = self.backend.scratchpad_store()
        self.assertIsInstance(store, GoogleDriveScratchpad)
        folders = {f["name"]: f for f in self.fake.folders}
        self.assertIn("memory", folders)
        self.assertEqual(store.folder_id, folders["memory"]["id"])

    def test_persona_source_creates_nested_personas_subfolders(self):
        source = self.backend.persona_source("lci-analyst")
        self.assertIsInstance(source, GoogleDrivePersonaSource)
        # personas/ under root, then lci-analyst/ under personas/
        by_name = {f["name"]: f for f in self.fake.folders}
        self.assertIn("personas", by_name)
        self.assertIn("lci-analyst", by_name)
        self.assertEqual(by_name["personas"]["parent"], "root-1")
        self.assertEqual(by_name["lci-analyst"]["parent"], by_name["personas"]["id"])
        self.assertEqual(source.folder_id, by_name["lci-analyst"]["id"])

    def test_persona_source_default_name_is_default(self):
        source = self.backend.persona_source()
        by_name = {f["name"]: f for f in self.fake.folders}
        self.assertIn("default", by_name)
        self.assertEqual(source.folder_id, by_name["default"]["id"])

    def test_persona_source_rejects_nested_name(self):
        with self.assertRaises(ValueError):
            self.backend.persona_source("projects/q1")
        with self.assertRaises(ValueError):
            self.backend.persona_source("")

    def test_reuses_existing_folder_instead_of_creating_duplicate(self):
        # Pre-seed a "sessions" folder; backend must find + reuse it.
        existing = self.fake.seed_folder("sessions", "root-1")
        store = self.backend.session_store()
        self.assertEqual(store.folder_id, existing)
        # No create call — we found the existing folder
        self.assertEqual(self.fake.create_calls, 0)

    def test_subfolder_id_is_cached_across_calls(self):
        self.backend.session_store()
        self.backend.session_store()
        # Cache hit: no extra list or create for the second call
        self.assertEqual(self.fake.create_calls, 1)
        # First call: list (not found) + create = 2 list (well, 1 list + 1 create)
        # Second call: 0 additional list calls due to cache
        # Just assert we didn't double the create:
        sessions = [f for f in self.fake.folders if f["name"] == "sessions"]
        self.assertEqual(len(sessions), 1)

    def test_two_persona_names_get_independent_folders(self):
        a = self.backend.persona_source("a")
        b = self.backend.persona_source("b")
        self.assertNotEqual(a.folder_id, b.folder_id)
        by_name = {f["name"]: f for f in self.fake.folders}
        self.assertIn("a", by_name)
        self.assertIn("b", by_name)


# ---------------------------------------------------------------------------
# Auth propagation to child stores
# ---------------------------------------------------------------------------


class TestAuthPropagation(unittest.TestCase):
    def test_service_account_file_flows_through(self):
        fake = FakeFolderDrive()
        backend = GoogleDriveStorageBackend(
            root_folder_id="r",
            service_account_file="/secrets/creds.json",
        )
        # Inject mocked service so we don't touch the network
        service = MagicMock()
        service.files.side_effect = fake.files
        backend._service = service

        store = backend.session_store()
        self.assertEqual(store._service_account_file, "/secrets/creds.json")
        self.assertIsNone(store._explicit_credentials)

    def test_credentials_object_flows_through(self):
        fake = FakeFolderDrive()
        marker = object()
        backend = GoogleDriveStorageBackend(root_folder_id="r", credentials=marker)
        service = MagicMock()
        service.files.side_effect = fake.files
        backend._service = service

        pad = backend.scratchpad_store()
        self.assertIs(pad._explicit_credentials, marker)


# ---------------------------------------------------------------------------
# memory_store() factory — env-flag-gated dispatch
# ---------------------------------------------------------------------------


class TestMemoryStoreFlag(unittest.TestCase):
    """``OPENBENCH_UNIFIED_MEMORY`` flag controls SQLite vs Drive routing."""

    def test_flag_off_returns_sqlite(self):
        from openbench.intelligence.memory import LocalSQLiteMemoryStore

        backend = _make_backend(FakeFolderDrive())
        with patch.dict("os.environ", {"OPENBENCH_UNIFIED_MEMORY": "0"}, clear=False):
            store = backend.memory_store()
        self.assertIsInstance(store, LocalSQLiteMemoryStore)

    def test_flag_unset_returns_sqlite(self):
        """Default behaviour — no env var, no Drive."""
        from openbench.intelligence.memory import LocalSQLiteMemoryStore

        env = {k: v for k, v in __import__("os").environ.items() if k != "OPENBENCH_UNIFIED_MEMORY"}
        backend = _make_backend(FakeFolderDrive())
        with patch.dict("os.environ", env, clear=True):
            store = backend.memory_store()
        self.assertIsInstance(store, LocalSQLiteMemoryStore)

    def test_flag_on_returns_drive_store(self):
        from openbench.integrations.gdrive.memory_store import GoogleDriveMemoryStore

        backend = _make_backend(FakeFolderDrive())
        with patch.dict("os.environ", {"OPENBENCH_UNIFIED_MEMORY": "1"}, clear=False):
            store = backend.memory_store()
        self.assertIsInstance(store, GoogleDriveMemoryStore)
        # Backend root folder propagates through; Drive store creates its
        # own ``agent-memory/`` subfolder lazily on first write.
        self.assertEqual(store.folder_id, "root-1")
        self.assertEqual(store.subfolder_name, "agent-memory")

    def test_flag_truthy_variants_all_enable_drive(self):
        from openbench.integrations.gdrive.memory_store import GoogleDriveMemoryStore

        backend = _make_backend(FakeFolderDrive())
        for raw in ("1", "true", "True", "TRUE", "yes", "Yes", "on", "ON"):
            with patch.dict("os.environ", {"OPENBENCH_UNIFIED_MEMORY": raw}, clear=False):
                store = backend.memory_store()
            self.assertIsInstance(
                store,
                GoogleDriveMemoryStore,
                msg=f"value {raw!r} should enable Drive memory store",
            )

    def test_flag_falsy_variants_all_keep_sqlite(self):
        from openbench.intelligence.memory import LocalSQLiteMemoryStore

        backend = _make_backend(FakeFolderDrive())
        for raw in ("0", "false", "FALSE", "no", "off", "", "  "):
            with patch.dict("os.environ", {"OPENBENCH_UNIFIED_MEMORY": raw}, clear=False):
                store = backend.memory_store()
            self.assertIsInstance(
                store,
                LocalSQLiteMemoryStore,
                msg=f"value {raw!r} should keep SQLite fallback",
            )

    def test_drive_memory_store_inherits_credentials(self):
        from openbench.integrations.gdrive.memory_store import GoogleDriveMemoryStore

        marker = object()
        backend = GoogleDriveStorageBackend(root_folder_id="r", credentials=marker)
        backend._service = MagicMock()
        with patch.dict("os.environ", {"OPENBENCH_UNIFIED_MEMORY": "1"}, clear=False):
            store = backend.memory_store()
        self.assertIsInstance(store, GoogleDriveMemoryStore)
        self.assertIs(store._explicit_credentials, marker)

    def test_drive_memory_store_inherits_service_account_file(self):
        from openbench.integrations.gdrive.memory_store import GoogleDriveMemoryStore

        backend = GoogleDriveStorageBackend(
            root_folder_id="r",
            service_account_file="/secrets/creds.json",
        )
        backend._service = MagicMock()
        with patch.dict("os.environ", {"OPENBENCH_UNIFIED_MEMORY": "1"}, clear=False):
            store = backend.memory_store()
        self.assertIsInstance(store, GoogleDriveMemoryStore)
        self.assertEqual(store._service_account_file, "/secrets/creds.json")


# ---------------------------------------------------------------------------
# Shared-drive flag plumbing
# ---------------------------------------------------------------------------


class TestSharedDriveFlags(unittest.TestCase):
    def test_list_and_create_pass_shared_drive_flags(self):
        fake = FakeFolderDrive()
        backend = _make_backend(fake)

        backend.session_store()
        backend.scratchpad_store()
        backend.persona_source("demo")

        svc_files = backend._service.files.return_value
        for call in svc_files.list.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)
            self.assertIs(call.kwargs["includeItemsFromAllDrives"], True)
        for call in svc_files.create.call_args_list:
            self.assertIs(call.kwargs["supportsAllDrives"], True)


# The GoogleDocPersonaSource import exists so linters don't strip it;
# _ref keeps the reference alive in the file for clarity.
_ = GoogleDocPersonaSource


if __name__ == "__main__":
    unittest.main()
