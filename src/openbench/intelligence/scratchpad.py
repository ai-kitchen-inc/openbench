"""User-editable markdown memory shared between agent and user.

A *scratchpad* is a persistent document the agent can read, write, and
append to via tools, and that the user can inspect or edit directly
with any text editor. This is distinct from:

- :class:`~openbench.intelligence.memory.MemoryStore` — append-only log
  of LLM ``Message`` objects, replayed into context on resume.
- :class:`~openbench.chat.session_store.SessionStore` — UI-level
  ``ChatSession`` snapshots with surfaces and attachments.

Scratchpad content is intended to live in a format that is meaningful
to both agent and human. Markdown is the conventional default.

Pillar placement (see ``docs/MENTAL_MODEL.md``): ``ScratchpadStore`` is
**plumbing under the Agentic pillar**, exposed to the LLM through the
``memory-scratchpad`` SDK skill. The store itself is infrastructure;
the *playbook* for when to use it is the skill (a Skill-pillar concern).

Example:
    >>> from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad
    >>> pad = LocalMarkdownScratchpad("~/.openbench/memory/")
    >>> pad.write("default", "- User prefers Indonesian for chat.")
    >>> pad.read("default")
    '- User prefers Indonesian for chat.'
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ScratchpadStore(ABC):
    """User-editable markdown memory, read/write by agent via tools.

    Contract:
    - ``read`` returns an empty string for unknown keys (not raise).
    - ``write`` overwrites existing content; creates the key if absent.
    - ``append`` creates the key if absent; newline-separates appends.
    - ``delete`` is idempotent (no-op for unknown keys).
    - ``list_keys`` returns keys in stable lexicographic order.
    """

    @abstractmethod
    def read(self, key: str = "default") -> str:
        """Read content for key. Returns empty string if key is absent.

        Args:
            key: The scratchpad key. Backends may interpret slashes as
                subdirectories or similar hierarchical notation.

        Returns:
            The key's content, or an empty string if it does not exist.
        """

    @abstractmethod
    def write(self, key: str, content: str) -> None:
        """Overwrite content for key (creates the key if absent).

        Args:
            key: The scratchpad key.
            content: The full replacement content.
        """

    @abstractmethod
    def append(self, key: str, content: str) -> None:
        """Append content to key (creates if absent).

        Implementations must newline-separate the existing content and
        the appended block so consecutive appends stay readable as
        distinct entries.

        Args:
            key: The scratchpad key.
            content: The content to append.
        """

    @abstractmethod
    def list_keys(self) -> list[str]:
        """List all available keys in lexicographic order."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key. No-op if the key is unknown.

        Args:
            key: The scratchpad key.
        """
