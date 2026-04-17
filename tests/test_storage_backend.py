"""Tests for StorageBackend Protocol, LocalStorageBackend, and default accessors."""

import tempfile
import unittest
from pathlib import Path

import openbench
from openbench import (
    LocalStorageBackend,
    StorageBackend,
    get_default_storage,
    set_default_storage,
)
from openbench.chat.session_store import SessionStore
from openbench.chat.stores.sqlite import SQLiteSessionStore
from openbench.intelligence.scratchpad import ScratchpadStore
from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad


class TestLocalStorageBackend(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.backend = LocalStorageBackend(self.root)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_root_created_on_init(self):
        deep = self.root / "nested" / "deep"
        LocalStorageBackend(deep)
        self.assertTrue(deep.exists())

    def test_session_store_returns_sqlite_impl(self):
        store = self.backend.session_store()
        self.assertIsInstance(store, SessionStore)
        self.assertIsInstance(store, SQLiteSessionStore)

    def test_session_store_uses_root_path(self):
        self.backend.session_store()
        self.assertTrue((self.root / "sessions.db").exists())

    def test_scratchpad_store_returns_markdown_impl(self):
        pad = self.backend.scratchpad_store()
        self.assertIsInstance(pad, ScratchpadStore)
        self.assertIsInstance(pad, LocalMarkdownScratchpad)

    def test_scratchpad_uses_memory_subdir(self):
        pad = self.backend.scratchpad_store()
        pad.write("k", "v")
        self.assertTrue((self.root / "memory" / "k.md").exists())

    def test_multiple_calls_return_independent_stores(self):
        a = self.backend.session_store()
        b = self.backend.session_store()
        self.assertIsNot(a, b)
        # But they should share the same underlying file.
        self.assertEqual(a.db_path, b.db_path)

    def test_conforms_to_protocol(self):
        self.assertIsInstance(self.backend, StorageBackend)

    def test_repr_contains_root(self):
        self.assertIn(str(self.root), repr(self.backend))


class TestDefaultStorageAccessors(unittest.TestCase):
    def setUp(self):
        # Reset any default the rest of the suite may have set
        self._prior = get_default_storage()
        set_default_storage(None)

    def tearDown(self):
        set_default_storage(self._prior)

    def test_default_is_none_by_default(self):
        self.assertIsNone(get_default_storage())

    def test_set_then_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalStorageBackend(tmpdir)
            set_default_storage(backend)
            self.assertIs(get_default_storage(), backend)

    def test_set_none_clears(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            set_default_storage(LocalStorageBackend(tmpdir))
            set_default_storage(None)
            self.assertIsNone(get_default_storage())

    def test_exported_from_top_level_package(self):
        # Make sure the names are actually in openbench's __all__/namespace
        self.assertTrue(hasattr(openbench, "LocalStorageBackend"))
        self.assertTrue(hasattr(openbench, "StorageBackend"))
        self.assertTrue(hasattr(openbench, "get_default_storage"))
        self.assertTrue(hasattr(openbench, "set_default_storage"))


class TestProtocolDuckTyping(unittest.TestCase):
    """Arbitrary objects conforming to the Protocol count as StorageBackend."""

    def test_minimal_duck(self):
        class Duck:
            def session_store(self):
                return SQLiteSessionStore(":memory:")

            def scratchpad_store(self):
                with tempfile.TemporaryDirectory() as tmpdir:
                    return LocalMarkdownScratchpad(tmpdir)

        self.assertIsInstance(Duck(), StorageBackend)

    def test_missing_method_fails_protocol_check(self):
        class NotABackend:
            def session_store(self):
                return None

            # missing scratchpad_store

        self.assertNotIsInstance(NotABackend(), StorageBackend)


if __name__ == "__main__":
    unittest.main()
