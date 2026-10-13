"""In-process fan-out of live dashboard events to SSE subscribers.

Each subscriber gets a bounded ``asyncio.Queue``; when a slow consumer falls
behind, the oldest pending event is dropped (every ``update`` carries the full
ViewModel, so skipping one is lossless).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

LiveEventType = Literal["snapshot", "update", "error", "closed"]

# A named event rather than an SSE comment: browsers' EventSource cannot
# observe comments, and a proxy may keep the client side open after the
# upstream died -- clients watch for this to detect a silently dead stream.
SSE_HEARTBEAT = "event: ping\ndata: {}\n\n"
SSE_HEARTBEAT_SECONDS = 15


@dataclass(frozen=True)
class LiveEvent:
    type: LiveEventType
    data: dict[str, Any] = field(default_factory=dict)


def format_sse(event: LiveEvent) -> str:
    """Encode one event as ``event:`` + single-line ``data:`` (JSON has no raw newlines)."""
    payload = json.dumps(event.data, ensure_ascii=False, default=str)
    return f"event: {event.type}\ndata: {payload}\n\n"


class LiveDashboardHub:
    """Pub/sub keyed by dashboard id. Publishing is loop-thread only; use
    ``publish_threadsafe`` from worker threads."""

    def __init__(self, *, max_queue: int = 16):
        self._max_queue = max(1, int(max_queue))
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, dashboard_id: str) -> asyncio.Queue:
        # Subscribing always happens on the serving loop; remember it so
        # worker threads can wake subscribers even if startup never ran
        # (TestClient) or bind_loop was skipped.
        if self._loop is None:
            with contextlib.suppress(RuntimeError):
                self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.setdefault(dashboard_id, set()).add(queue)
        return queue

    def unsubscribe(self, dashboard_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            queues = self._subscribers.get(dashboard_id)
            if not queues:
                return
            queues.discard(queue)
            if not queues:
                self._subscribers.pop(dashboard_id, None)

    def subscriber_count(self, dashboard_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(dashboard_id, ()))

    def publish(self, dashboard_id: str, event: LiveEvent) -> int:
        """Deliver to every subscriber; returns how many received it."""
        with self._lock:
            queues = list(self._subscribers.get(dashboard_id, ()))
        delivered = 0
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    continue
            delivered += 1
        return delivered

    def publish_threadsafe(self, dashboard_id: str, event: LiveEvent) -> None:
        """Schedule ``publish`` on the bound loop (direct call when unbound or on-loop)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            self.publish(dashboard_id, event)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self.publish(dashboard_id, event)
            return
        loop.call_soon_threadsafe(self.publish, dashboard_id, event)
