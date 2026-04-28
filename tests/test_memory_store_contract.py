"""SDK-side contract conformance tests for shipped MemoryStore impls.

Runs the public :class:`MemoryStoreContract` suite against every
SDK-shipped implementation so the bar third-party implementers
validate against is the same bar the SDK itself meets.

Currently covers:
- :class:`LocalSQLiteMemoryStore` (SQLite, local filesystem)

The Drive-backed conformance subclass lives in
``tests/test_memory_drive.py`` next to its in-memory ``FakeMemoryDrive``
helper — keeping the fixture and the subclass in the same file avoids
the otherwise-circular dependency between this file and the Drive
test module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from openbench.intelligence.memory import LocalSQLiteMemoryStore
from openbench.testing import MemoryStoreContract

if TYPE_CHECKING:
    from pathlib import Path


class TestLocalSQLiteMemoryStore(MemoryStoreContract):
    """Run the contract against :class:`LocalSQLiteMemoryStore`."""

    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path: Path) -> None:
        self._db_path = tmp_path / "test_memory.db"

    def make_store(self):
        return LocalSQLiteMemoryStore(db_path=str(self._db_path))

    def cleanup_store(self, store):
        # Each test gets a fresh tmp_path so no explicit cleanup needed —
        # but we still drop the connection reference defensively.
        del store
