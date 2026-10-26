"""Registry of built specialist agents, one per enabled profile.

Mirrors :class:`~general_chat.server.agent_holder.AgentHolder` semantics
for many agents: builds are lazy (``create_agent`` is expensive — it
constructs a vision sidecar and loads skills), cached per profile id,
and serialized per id so two concurrent first-requests build once.
``invalidate()`` drops cache entries; the next chat turn rebuilds from
the current profile row — the same "hot swap by atomic reference"
behavior admin persona saves rely on.

Descriptor reads never build agents: they come straight from the
profile store, so listing agents (router prompts, pickers) stays cheap.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from openbench.intelligence.protocol import AgentDescriptor, AgentDirectory

if TYPE_CHECKING:
    from collections.abc import Callable

    from general_chat.agent_store import AgentProfileRecord


def descriptor_from_profile(profile: AgentProfileRecord) -> AgentDescriptor:
    """Protocol descriptor for one profile (identity only, no build)."""
    return AgentDescriptor(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        model=profile.model,
    )


class AgentProfileRegistry:
    """Profile id -> lazily built agent, backed by the profile store."""

    def __init__(
        self,
        profile_store: Any,
        build_agent: Callable[[AgentProfileRecord], Any],
    ) -> None:
        self._store = profile_store
        self._build_agent = build_agent
        self._cache: dict[str, Any] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def profile(self, agent_id: str) -> AgentProfileRecord | None:
        """The enabled profile for ``agent_id``, or None."""
        if not agent_id:
            return None
        record = self._store.get(agent_id)
        return record if record is not None and record.enabled else None

    def profiles(self) -> list[AgentProfileRecord]:
        """All enabled profiles."""
        return [record for record in self._store.list() if record.enabled]

    def descriptors(self) -> list[AgentDescriptor]:
        """Descriptors of all enabled profiles — no agent construction."""
        return [descriptor_from_profile(record) for record in self.profiles()]

    def directory(self) -> AgentDirectory:
        """A fresh :class:`AgentDirectory` over the enabled profiles."""
        directory = AgentDirectory()
        for record in self.profiles():
            agent_id = record.id
            directory.register(descriptor_from_profile(record), lambda i=agent_id: self.get(i))
        return directory

    def get(self, agent_id: str) -> Any | None:
        """Build (once) and return the agent for an enabled profile.

        Returns None for unknown or disabled ids. A failed build leaves no
        cache entry — the exception propagates (callers surface it) and
        the next turn retries.
        """
        profile = self.profile(agent_id)
        if profile is None:
            return None
        cached = self._cache.get(profile.id)
        if cached is not None:
            return cached
        with self._lock_for(profile.id):
            cached = self._cache.get(profile.id)
            if cached is not None:
                return cached
            agent = self._build_agent(profile)
            self._cache[profile.id] = agent
            return agent

    def invalidate(self, agent_id: str | None = None) -> None:
        """Drop one cached agent (or all); next use rebuilds fresh."""
        if agent_id is None:
            self._cache.clear()
        else:
            self._cache.pop(agent_id.strip().lower(), None)

    def _lock_for(self, agent_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(agent_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[agent_id] = lock
            return lock
