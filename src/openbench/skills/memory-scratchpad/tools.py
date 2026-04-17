"""Tools for the memory-scratchpad skill.

All tools operate against a single module-level :class:`ScratchpadStore`
reference that the agent sets via :func:`bind` during construction.
This DI hook (see §6 of the storage-layer RFC) keeps the tool
callables stateless from the caller's perspective while still letting
different agents in the same process bind to different stores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbench.intelligence.scratchpad import ScratchpadStore


_store: ScratchpadStore | None = None


def bind(scratchpad: ScratchpadStore | None = None, **_: object) -> None:
    """Inject the ScratchpadStore the agent was configured with.

    Called by :meth:`SkillRegistry.bind` during :class:`BaseAgent`
    construction. Extra keyword arguments are ignored so future
    bindings can be added without breaking this skill.
    """
    global _store
    _store = scratchpad


def _require_store() -> ScratchpadStore:
    if _store is None:
        raise RuntimeError(
            "memory-scratchpad skill is not bound. Pass scratchpad= to "
            "BaseAgent, or configure a StorageBackend that provides a "
            "scratchpad_store()."
        )
    return _store


# ---------------------------------------------------------------------------
# Tools (convention: FOO_SCHEMA + foo() pair discovered by SkillRegistry)
# ---------------------------------------------------------------------------


READ_MEMORY_SCHEMA: dict = {
    "name": "read_memory",
    "description": (
        "Read the content of a scratchpad memory key. Returns the "
        "current markdown text, or an empty string if the key has "
        "nothing stored yet."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": (
                    "Memory key. Use 'default' for general notes or a "
                    "named topic (e.g. 'preferences', 'projects/q1')."
                ),
                "default": "default",
            }
        },
        "required": [],
    },
}


def read_memory(key: str = "default") -> str:
    """Return the current content of the scratchpad key."""
    return _require_store().read(key)


WRITE_MEMORY_SCHEMA: dict = {
    "name": "write_memory",
    "description": (
        "Overwrite a scratchpad memory key with new content. Use this "
        "to replace existing notes. Prefer append_memory when adding "
        "to an ongoing list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Memory key to overwrite.",
            },
            "content": {
                "type": "string",
                "description": "New markdown content that replaces the key.",
            },
        },
        "required": ["key", "content"],
    },
}


def write_memory(key: str, content: str) -> str:
    """Overwrite the scratchpad key and return a confirmation string."""
    _require_store().write(key, content)
    return f"wrote {len(content)} chars to {key}"


APPEND_MEMORY_SCHEMA: dict = {
    "name": "append_memory",
    "description": (
        "Append a new block of markdown to a scratchpad key, separated "
        "from existing content by a newline. Creates the key if it "
        "does not exist."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Memory key to append to.",
            },
            "content": {
                "type": "string",
                "description": "Markdown block to append.",
            },
        },
        "required": ["key", "content"],
    },
}


def append_memory(key: str, content: str) -> str:
    """Append to the scratchpad key and return a confirmation string."""
    _require_store().append(key, content)
    return f"appended {len(content)} chars to {key}"


LIST_MEMORY_KEYS_SCHEMA: dict = {
    "name": "list_memory_keys",
    "description": (
        "List all available scratchpad memory keys. Use this before "
        "reading when you are not sure which keys exist."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def list_memory_keys() -> list[str]:
    """Return all available scratchpad keys."""
    return _require_store().list_keys()
