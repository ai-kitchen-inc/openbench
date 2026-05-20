"""Filesystem-backed ScratchpadStore.

Maps each scratchpad key to a ``.md`` file under a configurable root
directory. Slashes in keys are interpreted as subdirectories so agents
can organize memory hierarchically (e.g. ``"projects/lci-q1"``).

Security constraints (§9 of the storage-layer RFC):
- Keys containing ``..`` are rejected (path traversal).
- Absolute-path keys are rejected.
- Symlinks inside the scratchpad tree are rejected on read/write.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from openbench.intelligence.scratchpad import ScratchpadStore

logger = logging.getLogger(__name__)

_FILE_EXT = ".md"


def _validate_key(key: str) -> str:
    """Return the key unchanged after validating it is safe to use as a path.

    Raises:
        ValueError: If the key is empty, absolute, or contains ``..``.
    """
    if not key:
        raise ValueError("scratchpad key must be a non-empty string")
    if "\x00" in key:
        raise ValueError(f"scratchpad key contains a NUL byte: {key!r}")
    # Normalize slashes so Windows-style paths also get checked.
    normalized = key.replace("\\", "/")
    parts = normalized.split("/")
    if any(p in ("", "..", ".") for p in parts):
        raise ValueError(f"scratchpad key must not contain '..', '.', or empty segments: {key!r}")
    if normalized.startswith("/"):
        raise ValueError(f"scratchpad key must be relative, not absolute: {key!r}")
    return key


class LocalMarkdownScratchpad(ScratchpadStore):
    """Local filesystem scratchpad mapping keys to markdown files.

    Default root is ``~/.openbench/memory/`` — the SDK-wide shared
    memory location. Callers can pass a project-scoped root (e.g.
    ``./.openbench/memory/``) for per-project isolation.

    File layout::

        {root}/
        ├── default.md          # key="default"
        ├── preferences.md      # key="preferences"
        └── projects/
            └── lci-q1.md       # key="projects/lci-q1"
    """

    def __init__(self, root: str | Path = "~/.openbench/memory/"):
        """Initialize the scratchpad, creating the root directory if absent.

        Args:
            root: Directory under which markdown files are stored.
                Tilde expansion is applied.
        """
        self.root = _expand_user_path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        """Translate a validated key to an absolute file path.

        Also verifies that the final path is contained within the
        scratchpad root (belt-and-suspenders against symlink tricks
        combined with key validation).
        """
        _validate_key(key)
        path = self.root / f"{key}{_FILE_EXT}"
        resolved = path.resolve() if path.exists() else path
        # Containment check — compare resolved path against resolved root.
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"scratchpad key {key!r} resolves outside the scratchpad root"
            ) from exc
        if path.is_symlink():
            raise ValueError(
                f"scratchpad file for key {key!r} is a symlink — rejected for security"
            )
        return path

    def read(self, key: str = "default") -> str:
        """Read content for key; returns empty string if the file is absent."""
        path = self._path_for(key)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write(self, key: str, content: str) -> None:
        """Overwrite content for key, creating parent directories if needed."""
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def append(self, key: str, content: str) -> None:
        """Append content to key (newline-separated), creating the file if absent.

        Existing content without a trailing newline gets one inserted so
        appended blocks don't run on.
        """
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            separator = "" if existing.endswith("\n") or not existing else "\n"
            path.write_text(existing + separator + content, encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")

    def list_keys(self) -> list[str]:
        """Return all scratchpad keys in lexicographic order.

        Walks the root directory and reports every ``.md`` file, using
        the relative path (minus extension) as the key.
        """
        keys: list[str] = []
        for md in self.root.rglob(f"*{_FILE_EXT}"):
            if md.is_symlink():
                continue
            rel = md.relative_to(self.root).with_suffix("")
            keys.append(rel.as_posix())
        return sorted(keys)

    def delete(self, key: str) -> None:
        """Delete the file backing a key. No-op if the file is absent."""
        path = self._path_for(key)
        if path.exists():
            path.unlink()


def _expand_user_path(path: str | Path) -> Path:
    raw = str(path)
    home = os.environ.get("HOME")
    if home and (raw == "~" or raw.startswith("~/") or raw.startswith("~\\")):
        suffix = raw[2:] if len(raw) > 1 else ""
        return Path(home, suffix)
    return Path(path).expanduser()
