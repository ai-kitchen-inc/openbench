"""Per-turn owner, published to skill tools through a ContextVar.

The chat handler sets it when a stream starts; tools bound once at agent
construction read it per call. ``ToolExecutor`` copies the context into its
worker threads, so concurrent turns never see each other's owner.
"""

from __future__ import annotations

from contextvars import ContextVar

_TURN_OWNER: ContextVar[str | None] = ContextVar("openbench_turn_owner", default=None)


def set_turn_owner(owner: str | None) -> None:
    """Record the owner of the chat turn that is about to run."""
    _TURN_OWNER.set(owner or None)


def current_turn_owner() -> str | None:
    """Owner of the current chat turn, or ``None`` outside a turn."""
    return _TURN_OWNER.get()
