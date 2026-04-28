"""In-process LRU cache for :class:`GoogleDriveMemoryStore`.

v1.5 (RFC-UNIFIED-MEMORY-STORAGE Phase 2 follow-up): a TTL-based
message cache so repeated ``load()`` calls within the freshness window
skip the Drive download round-trip. Saves a meaningful chunk of
latency on chat replays where the same session is read many times in a
row (sidebar render → message list render → in-memory access during
streaming).

The class is named ``_EtagCache`` to match RFC §6.8 wording and to
leave room for ETag/version validation in a follow-up — but v1.5 does
no remote validation: cached entries are simply trusted until their
TTL expires, then evicted on the next access. The cross-device
handoff case still works because each backend instance has its own
cache (so a save on one instance does not need to invalidate caches on
another — the other instance's cache simply ages out within
``ttl_seconds``).

Thread-safe via a single lock around the OrderedDict — entries are
small (lists of Message objects), so contention is dominated by Drive
I/O elsewhere, not by this lock.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbench.intelligence.base import Message

__all__ = ["_EtagCache"]


@dataclass
class _CacheEntry:
    """Cached message list with its expiry time.

    ``messages`` is a tuple — immutability prevents callers from
    accidentally mutating the cached list and corrupting the cache.
    Callers receive a fresh list copy on every successful ``get``.
    """

    messages: tuple[Message, ...]
    expires_at: float


class _EtagCache:
    """LRU + TTL cache of session_id -> Message history.

    Args:
        max_sessions: Soft upper bound on cache size. Excess entries
            are evicted in least-recently-used order on ``put``.
        ttl_seconds: Entries are treated as fresh for this long after
            insertion or the most recent ``put``. After expiry,
            ``get`` returns ``None`` and the entry is dropped on the
            next access.
    """

    def __init__(self, *, max_sessions: int = 100, ttl_seconds: float = 30.0):
        if max_sessions <= 0:
            raise ValueError("max_sessions must be > 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._max_sessions = max_sessions
        self._ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[Message] | None:
        """Return a fresh copy of cached messages, or ``None`` on miss/expiry.

        On hit: the entry is marked most-recently-used and a fresh
        ``list`` (not a reference to the cached tuple) is returned, so
        callers may mutate the result without corrupting the cache.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(session_id)
            if entry is None:
                return None
            if entry.expires_at <= now:
                # Stale — drop and miss.
                self._cache.pop(session_id, None)
                return None
            self._cache.move_to_end(session_id)
            return list(entry.messages)

    def put(self, session_id: str, messages: list[Message]) -> None:
        """Insert or refresh a cache entry. Resets the TTL clock."""
        expires_at = time.monotonic() + self._ttl_seconds
        with self._lock:
            self._cache[session_id] = _CacheEntry(
                messages=tuple(messages),
                expires_at=expires_at,
            )
            self._cache.move_to_end(session_id)
            while len(self._cache) > self._max_sessions:
                self._cache.popitem(last=False)

    def invalidate(self, session_id: str) -> None:
        """Drop a single entry. Idempotent — no-op if absent."""
        with self._lock:
            self._cache.pop(session_id, None)

    def clear(self) -> None:
        """Drop every cached entry."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, session_id: object) -> bool:
        if not isinstance(session_id, str):
            return False
        with self._lock:
            return session_id in self._cache
