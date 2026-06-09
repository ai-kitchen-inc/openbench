"""Backend-agnostic source for persona content.

A :class:`PersonaSource` returns the three canonical markdown sections
a :class:`~openbench.intelligence.persona.Persona` is composed from:

- ``soul``  — SOUL.md (identity, worldview, boundaries)
- ``style`` — STYLE.md (voice, language, formatting)
- ``agents`` — AGENTS.md (operational rules, tool usage)

The ABC is deliberately minimal (one method, ``fetch(key)``) so that
any backend — filesystem, Google Doc, HTTP URL, Notion page — can
implement it without inheriting unrelated behavior. New backends land
as separate classes without changing :class:`Persona` itself.

Pillar placement (see ``docs/MENTAL_MODEL.md``): ``PersonaSource`` is
**plumbing under the Agentic pillar**. ``Persona`` itself is part of
the Agentic pillar (agent identity); ``PersonaSource`` is just where
the persona's markdown content is read from. Read-only, off the
hot-path — but the same "Protocol-based ABC, not MCP" rule applies.

Example:
    >>> from openbench.intelligence.persona_source import InlinePersonaSource
    >>> from openbench.intelligence.persona import Persona
    >>> source = InlinePersonaSource(soul="You are a helpful analyst.")
    >>> persona = Persona.from_source(source)
    >>> persona.compose()
    'You are a helpful analyst.'
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

__all__ = [
    "FilesystemPersonaSource",
    "InlinePersonaSource",
    "PersonaSource",
]


class PersonaSource(ABC):
    """Source of persona section content keyed by SOUL/STYLE/AGENTS.

    Contract:
    - ``fetch(key)`` returns the content for a known key, or an empty
      string if the key is not provided by this backend.
    - ``available_keys()`` reports which keys this source can serve;
      the default implementation returns all three canonical keys.
    """

    KEYS: tuple[str, ...] = ("soul", "style", "agents")

    @abstractmethod
    def fetch(self, key: str) -> str:
        """Return the content for ``key``, or an empty string if absent.

        Implementations must not raise for unknown keys — they return
        an empty string so callers can safely request every KEY.
        """

    def available_keys(self) -> list[str]:
        """Return the keys this source is willing to serve."""
        return list(self.KEYS)


class FilesystemPersonaSource(PersonaSource):
    """Read SOUL.md / STYLE.md / AGENTS.md from a local directory.

    Mirrors the security posture of :meth:`Persona.from_dir`:
    - Missing files resolve to an empty string for that key.
    - Symlinks are rejected (anti-traversal).
    - Content is read as UTF-8 and ``.strip()``-ed.
    """

    _FILE_MAP: dict[str, str] = {
        "soul": "SOUL.md",
        "style": "STYLE.md",
        "agents": "AGENTS.md",
    }

    def __init__(self, path: str | Path):
        """Initialize with the directory containing the persona files.

        Args:
            path: Directory containing SOUL.md / STYLE.md / AGENTS.md.

        Raises:
            FileNotFoundError: If the directory does not exist.
        """
        self.path = _expand_user_path(path)
        if not self.path.is_dir():
            raise FileNotFoundError(f"Persona directory not found: {self.path}")

    def fetch(self, key: str) -> str:
        """Return content for a persona key. Empty string if missing."""
        filename = self._FILE_MAP.get(key)
        if filename is None:
            return ""
        f = self.path / filename
        if not f.exists():
            return ""
        if f.is_symlink():
            raise ValueError(
                f"Persona file {filename} is a symlink — rejected for security. "
                f"Use a regular file instead: {f}"
            )
        return f.read_text(encoding="utf-8").strip()

    def __repr__(self) -> str:
        return f"FilesystemPersonaSource(path={str(self.path)!r})"


class InlinePersonaSource(PersonaSource):
    """Persona backed by in-memory strings — useful for tests and dynamic composition.

    Example:
        >>> source = InlinePersonaSource(
        ...     soul="I am an LCA analyst.",
        ...     agents="Always call xql_catalog first.",
        ... )
        >>> source.fetch("soul")
        'I am an LCA analyst.'
        >>> source.fetch("style")
        ''
    """

    def __init__(
        self,
        soul: str = "",
        style: str = "",
        agents: str = "",
    ):
        self._values: dict[str, str] = {
            "soul": soul,
            "style": style,
            "agents": agents,
        }

    def fetch(self, key: str) -> str:
        """Return the inline content for ``key``, or empty string."""
        return self._values.get(key, "")

    def __repr__(self) -> str:
        filled = [k for k, v in self._values.items() if v]
        return f"InlinePersonaSource(keys={filled!r})"


def _expand_user_path(path: str | Path) -> Path:
    raw = str(path)
    home = os.environ.get("HOME")
    if home and (raw == "~" or raw.startswith(("~/", "~\\"))):
        suffix = raw[2:] if len(raw) > 1 else ""
        return Path(home, suffix)
    return Path(path).expanduser()
