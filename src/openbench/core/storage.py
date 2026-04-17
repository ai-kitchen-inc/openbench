"""Storage backend protocol that bundles session, scratchpad, and
(eventually) persona storage behind a single factory.

Three ABCs live elsewhere and can be used independently:

- :class:`~openbench.chat.session_store.SessionStore`
- :class:`~openbench.intelligence.scratchpad.ScratchpadStore`
- :class:`~openbench.intelligence.persona_source.PersonaSource` (M3)

Implementing each separately is fine for mixed deployments. But the
common case — "put everything on the same backend" — wants a single
configuration point. :class:`StorageBackend` is that factory.

The Protocol is runtime-checkable so tests can assert conformance
without forcing impls to inherit a base class:

    >>> from openbench.core.storage import StorageBackend, LocalStorageBackend
    >>> isinstance(LocalStorageBackend("/tmp/ob"), StorageBackend)
    True

Note:
    ``persona_source`` lands in Milestone 3 of the storage-layer RFC.
    Until then, the Protocol covers only session + scratchpad.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from openbench.chat.session_store import SessionStore
    from openbench.intelligence.scratchpad import ScratchpadStore


__all__ = ["LocalStorageBackend", "StorageBackend"]


@runtime_checkable
class StorageBackend(Protocol):
    """Factory for all storage stores an OpenBench app may need.

    Implementations produce a :class:`SessionStore` and a
    :class:`ScratchpadStore` rooted at a single logical location — a
    local directory, a cloud bucket, a Notion workspace, etc. A future
    ``persona_source(name)`` method will be added in M3.
    """

    def session_store(self) -> SessionStore: ...

    def scratchpad_store(self) -> ScratchpadStore: ...


class LocalStorageBackend:
    """SDK-shipped default backend that stores everything on the local filesystem.

    Layout (root=``~/.openbench/``)::

        ~/.openbench/
        ├── sessions.db         # SQLiteSessionStore
        └── memory/             # LocalMarkdownScratchpad
            └── <key>.md

    Project-scoped usage — pass ``./.openbench/`` to isolate storage to
    the current working directory:

        >>> backend = LocalStorageBackend("./.openbench/")

    All produced stores are created lazily: constructing a backend does
    not open database connections or touch the filesystem beyond
    creating the root directory.
    """

    def __init__(self, root: str | Path = "~/.openbench/"):
        """Initialize the backend, creating the root directory if absent.

        Args:
            root: Directory under which all storage lives. Tilde
                expansion is applied.
        """
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def session_store(self) -> SessionStore:
        """Return a SQLite-backed :class:`SessionStore` at ``<root>/sessions.db``."""
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        return SQLiteSessionStore(db_path=str(self.root / "sessions.db"))

    def scratchpad_store(self) -> ScratchpadStore:
        """Return a markdown-backed :class:`ScratchpadStore` at ``<root>/memory/``."""
        from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad

        return LocalMarkdownScratchpad(root=self.root / "memory")

    def __repr__(self) -> str:
        return f"LocalStorageBackend(root={str(self.root)!r})"
