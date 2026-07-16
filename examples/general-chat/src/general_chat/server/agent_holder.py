"""Mutable holder for the shared chat agent, enabling hot rebuilds.

The agent is expensive, shared, and (by SDK design) immutable with
respect to its persona — applying a new persona requires constructing
a new :class:`BaseAgent`. Request handlers snapshot ``holder.agent``
per request (and the chat handler ``copy.copy``s it per turn), so an
atomic reference swap is race-free: in-flight streams keep the old
object, new requests pick up the new one.

``create_agent`` re-attaches registry MCP tools itself (it ends with
``reload_external_mcp_tools``), so a factory call returns a fully
wired agent.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class AgentHolder:
    """Holds the current shared agent; rebuilds are serialized."""

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._lock = threading.Lock()
        self.agent = factory()

    def rebuild(self) -> Any:
        """Build a fresh agent and swap it in.

        The factory raising leaves the previous agent serving — the
        exception propagates to the caller (admin endpoint returns it
        as a 500 and nothing changes).
        """
        with self._lock:
            new_agent = self._factory()
            self.agent = new_agent
            return new_agent
