"""Tiny in-memory rate limiter for auth endpoints.

We only rate limit the couple of endpoints that hit Google's OAuth
infrastructure (``/auth/drive/connect``) — those are the only ones where
repeated misuse is expensive (Google quota cost) or dangerous (brute
forcing). All other endpoints are cheap and Firebase itself already
throttles sign-in attempts.

The bucket is process-local, which is good enough for:

- single-replica demo deployments (the common case for lci-mini), and
- slowing down noisy misconfigured clients that spam connect() in a loop.

For multi-replica prod you'd swap this out for Redis or Firestore with
the same interface. Caller keeps a :class:`RateLimiter` instance, calls
``check(key)`` on each request, and lets a :class:`RateLimited` exception
propagate into FastAPI's exception handler.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


class RateLimited(Exception):
    """Raised by :meth:`RateLimiter.check` when the key is over quota.

    Attributes:
        retry_after_s: Seconds the client should wait before retrying.
        limit: The configured bucket capacity.
        window_s: The configured bucket window length in seconds.
    """

    def __init__(self, retry_after_s: float, limit: int, window_s: float) -> None:
        self.retry_after_s = max(0.0, float(retry_after_s))
        self.limit = limit
        self.window_s = window_s
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window_s:.0f}s "
            f"(retry in {self.retry_after_s:.1f}s)"
        )


@dataclass
class RateLimiter:
    """Sliding-window rate limiter.

    Args:
        limit: Max requests allowed per ``window_s`` seconds.
        window_s: Window length in seconds.

    Example:
        >>> rl = RateLimiter(limit=10, window_s=3600)
        >>> rl.check("uid-abc")  # allowed
        >>> # ... 10 more times raises RateLimited
    """

    limit: int
    window_s: float

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("limit must be > 0")
        if self.window_s <= 0:
            raise ValueError("window_s must be > 0")
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> None:
        """Record a request for ``key`` and raise if over quota.

        Use a distinctive key — ``f"connect:{uid}"`` is better than
        ``uid`` because the same uid might hit multiple rate-limited
        endpoints with different budgets.
        """
        t = time.monotonic() if now is None else now
        cutoff = t - self.window_s
        with self._lock:
            q = self._events[key]
            # Drop expired entries from the left.
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                oldest = q[0]
                retry_after = (oldest + self.window_s) - t
                raise RateLimited(
                    retry_after_s=retry_after,
                    limit=self.limit,
                    window_s=self.window_s,
                )
            q.append(t)

    def reset(self, key: str | None = None) -> None:
        """Clear counters. Primarily for tests; also safe to call at SIGHUP."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


# Module-level default limiter for /auth/drive/connect.
#
# 10 attempts / hour is intentionally generous for humans (Drive
# connection is a one-time action) but tight enough to catch a client
# stuck in a retry loop.
_DRIVE_CONNECT_LIMITER = RateLimiter(limit=10, window_s=3600.0)


def get_drive_connect_limiter() -> RateLimiter:
    """Return the process-wide limiter for ``/auth/drive/connect``."""
    return _DRIVE_CONNECT_LIMITER
