"""Storage backend protocol that bundles session, scratchpad, and
(eventually) persona storage behind a single factory.

In the four-pillar mental model (see ``docs/MENTAL_MODEL.md``), the
storage layer is **plumbing under the Agentic pillar** — not a pillar
itself. The agent never decides to use it; it always does. Users never
reason about which backend is mounted; they just expect their
conversation and files to be there next time. That framing is why the
storage layer stays as Protocol-based ABCs rather than being exposed as
MCP servers: hot-path latency, transactional semantics, and per-request
auth fan-out are not things MCP handles well.

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
    from openbench.chat.files import FileStore
    from openbench.chat.session_store import SessionStore
    from openbench.intelligence.memory import MemoryStore
    from openbench.intelligence.persona_source import PersonaSource
    from openbench.intelligence.scratchpad import ScratchpadStore


__all__ = ["LocalStorageBackend", "StorageBackend"]


@runtime_checkable
class StorageBackend(Protocol):
    """Factory for all storage stores an OpenBench app may need.

    Implementations produce a :class:`SessionStore`, a
    :class:`ScratchpadStore`, and a :class:`PersonaSource` all rooted
    at a single logical location — a local directory, a cloud bucket,
    a Notion workspace, etc.

    The ``name`` argument to :meth:`persona_source` identifies which
    persona to load when a backend hosts multiple (e.g.
    ``"lci-analyst"`` vs ``"code-reviewer"`` in the same Drive folder).
    Default is ``"default"``.
    """

    def session_store(self) -> SessionStore: ...

    def memory_store(self) -> MemoryStore:
        """Store for LLM-internal agent conversation memory.

        Distinct from :meth:`session_store`: session is the UI-facing
        chat transcript (user + assistant final text), while memory is
        the LLM-internal turn history including tool_calls and tool
        responses. Same session_id links the two — but they can use
        different backends (e.g. Drive for sessions, Postgres for
        memory).

        See the RFC-UNIFIED-MEMORY-STORAGE document for the full
        backend-agnostic composition pattern.
        """
        ...

    def scratchpad_store(self) -> ScratchpadStore: ...

    def persona_source(self, name: str = "default") -> PersonaSource: ...

    def file_store(self) -> FileStore:
        """Store for user-uploaded chat attachments (``uploads/``)."""
        ...

    def output_store(self) -> FileStore:
        """Store for agent-produced downloadable artifacts (``downloads/``).

        Same contract as :meth:`file_store` — different folder. Used by
        export-excel, pdf-tools, and any other skill that writes a file
        the frontend should be able to download.
        """
        ...


class LocalStorageBackend:
    """SDK-shipped default backend that stores everything on the local filesystem.

    Layout (root=``~/.openbench/``)::

        ~/.openbench/
        ├── sessions.db         # SQLiteSessionStore
        ├── memory.db           # LocalSQLiteMemoryStore (agent memory)
        ├── memory/             # LocalMarkdownScratchpad (user-editable)
        │   └── <key>.md
        └── personas/           # FilesystemPersonaSource, per-name
            └── <name>/
                ├── SOUL.md
                ├── STYLE.md
                └── AGENTS.md

    Note: the ``memory/`` directory (scratchpad) and ``memory.db``
    (agent memory) are distinct — the former is user-facing markdown
    the agent reads/writes via the memory-scratchpad skill, the latter
    is LLM-internal turn history.

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

    def memory_store(self) -> MemoryStore:
        """Return a SQLite-backed :class:`MemoryStore` at ``<root>/memory.db``.

        Shipped as :class:`LocalSQLiteMemoryStore` — a thin alias for
        the pre-existing :class:`SQLiteMemoryStore` that follows the
        ``Local<Technology><Concept>Store`` naming convention used by
        the other storage classes.
        """
        from openbench.intelligence.memory import LocalSQLiteMemoryStore

        return LocalSQLiteMemoryStore(db_path=str(self.root / "memory.db"))

    def scratchpad_store(self) -> ScratchpadStore:
        """Return a markdown-backed :class:`ScratchpadStore` at ``<root>/memory/``."""
        from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad

        return LocalMarkdownScratchpad(root=self.root / "memory")

    def persona_source(self, name: str = "default") -> PersonaSource:
        """Return a :class:`FilesystemPersonaSource` at ``<root>/personas/<name>/``.

        Creates the directory if absent so callers can inspect or edit
        the persona files immediately after construction. The directory
        starts empty — missing SOUL.md / STYLE.md / AGENTS.md files
        resolve to empty sections when fetched.
        """
        from openbench.intelligence.persona_source import FilesystemPersonaSource

        persona_dir = self.root / "personas" / name
        persona_dir.mkdir(parents=True, exist_ok=True)
        return FilesystemPersonaSource(persona_dir)

    def file_store(self) -> FileStore:
        """Return a disk-backed :class:`FileStore` at ``<root>/uploads/``."""
        from openbench.chat.files import LocalFileStore

        return LocalFileStore(upload_dir=str(self.root / "uploads"))

    def output_store(self) -> FileStore:
        """Return a disk-backed :class:`FileStore` at ``<root>/downloads/``."""
        from openbench.chat.files import LocalFileStore

        return LocalFileStore(upload_dir=str(self.root / "downloads"))

    def __repr__(self) -> str:
        return f"LocalStorageBackend(root={self.root})"
