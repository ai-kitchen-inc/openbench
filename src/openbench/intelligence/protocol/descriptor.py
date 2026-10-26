"""Agent descriptors and the instance-level agent directory.

The protocol layer coordinates *configured agent instances* — unlike
:class:`~openbench.core.registry.PluginRegistry`, which registers classes.
An :class:`AgentDescriptor` is the routable identity card of one agent
(who it is, what it is good at); an :class:`AgentDirectory` maps those
descriptors to lazy ``resolve()`` callables returning the actual agent
(an :class:`~openbench.core.abstractions.Agent` or a framework adapter —
:class:`~openbench.chat.ChatEngine` accepts both).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class AgentDescriptor:
    """Routable identity of one configured agent.

    Attributes:
        id: Stable slug identifying the agent (e.g. ``"finance-analyst"``).
        name: Human-readable display name.
        description: What the agent is good at — feeds the router prompt,
            so it should read like a dispatch hint, not marketing copy.
        tags: Optional free-form capability tags.
        model: Optional model name the agent runs on (informational).
    """

    id: str
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    model: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("AgentDescriptor.id must be a non-empty string")
        if not self.name or not self.name.strip():
            raise ValueError("AgentDescriptor.name must be a non-empty string")


@dataclass
class _DirectoryEntry:
    descriptor: AgentDescriptor
    resolve: Callable[[], Any]
    _cached: Any = field(default=None, repr=False)


class AgentDirectory:
    """Thread-safe directory of configured agents, keyed by descriptor id.

    ``resolve`` callables are invoked lazily on first :meth:`resolve` and
    the result is cached, so registering an expensive-to-build agent costs
    nothing until it is actually dispatched to.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _DirectoryEntry] = {}

    def register(self, descriptor: AgentDescriptor, resolve: Callable[[], Any]) -> None:
        """Register an agent. Raises ``ValueError`` on a duplicate id."""
        with self._lock:
            if descriptor.id in self._entries:
                raise ValueError(f"Agent id already registered: {descriptor.id!r}")
            self._entries[descriptor.id] = _DirectoryEntry(descriptor, resolve)

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent; returns whether it was present."""
        with self._lock:
            return self._entries.pop(agent_id, None) is not None

    def get(self, agent_id: str) -> AgentDescriptor | None:
        """Return the descriptor for ``agent_id``, or None."""
        with self._lock:
            entry = self._entries.get(agent_id)
            return entry.descriptor if entry else None

    def resolve(self, agent_id: str) -> Any | None:
        """Build (once) and return the agent behind ``agent_id``, or None."""
        with self._lock:
            entry = self._entries.get(agent_id)
        if entry is None:
            return None
        # Build outside the directory lock: resolve() may be expensive and
        # must not serialize unrelated lookups. A rare double build is
        # harmless; the last one wins.
        if entry._cached is None:
            entry._cached = entry.resolve()
        return entry._cached

    def descriptors(self) -> list[AgentDescriptor]:
        """All registered descriptors, in registration order."""
        with self._lock:
            return [entry.descriptor for entry in self._entries.values()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, agent_id: object) -> bool:
        with self._lock:
            return agent_id in self._entries
