"""Tests for the in-memory rate limiter powering /auth/drive/connect.

The tests inject a controlled clock via the ``now=`` parameter so we
don't depend on wall time or sleep in tests.
"""

from __future__ import annotations

import pytest
from lci_mini.auth.rate_limit import (
    RateLimited,
    RateLimiter,
    get_drive_connect_limiter,
)


class TestRateLimiter:
    def test_allows_up_to_limit(self):
        rl = RateLimiter(limit=3, window_s=10.0)
        # 3 requests succeed at t=0
        for _ in range(3):
            rl.check("uid-a", now=0.0)

    def test_rejects_over_limit(self):
        rl = RateLimiter(limit=3, window_s=10.0)
        for _ in range(3):
            rl.check("uid-a", now=0.0)
        with pytest.raises(RateLimited) as exc:
            rl.check("uid-a", now=0.0)
        assert exc.value.retry_after_s == pytest.approx(10.0, abs=0.01)
        assert exc.value.limit == 3
        assert exc.value.window_s == 10.0

    def test_window_slides(self):
        rl = RateLimiter(limit=2, window_s=10.0)
        rl.check("uid-a", now=0.0)
        rl.check("uid-a", now=5.0)
        with pytest.raises(RateLimited):
            rl.check("uid-a", now=6.0)
        # After t=10.1 the first request has expired.
        rl.check("uid-a", now=10.1)

    def test_keys_are_isolated(self):
        rl = RateLimiter(limit=1, window_s=10.0)
        rl.check("uid-a", now=0.0)
        # Different key has its own bucket.
        rl.check("uid-b", now=0.0)
        with pytest.raises(RateLimited):
            rl.check("uid-a", now=0.0)

    def test_reset_key(self):
        rl = RateLimiter(limit=1, window_s=10.0)
        rl.check("uid-a", now=0.0)
        rl.reset("uid-a")
        rl.check("uid-a", now=0.0)  # allowed again after reset

    def test_reset_all(self):
        rl = RateLimiter(limit=1, window_s=10.0)
        rl.check("uid-a", now=0.0)
        rl.check("uid-b", now=0.0)
        rl.reset()
        rl.check("uid-a", now=0.0)
        rl.check("uid-b", now=0.0)

    def test_invalid_constructor_args(self):
        with pytest.raises(ValueError):
            RateLimiter(limit=0, window_s=10.0)
        with pytest.raises(ValueError):
            RateLimiter(limit=10, window_s=0.0)

    def test_retry_after_shrinks_as_time_passes(self):
        rl = RateLimiter(limit=1, window_s=10.0)
        rl.check("uid-a", now=0.0)
        with pytest.raises(RateLimited) as exc:
            rl.check("uid-a", now=3.0)
        # Oldest event at t=0, window=10, now=3 → retry_after = 7
        assert exc.value.retry_after_s == pytest.approx(7.0, abs=0.01)


class TestModuleSingleton:
    def test_returns_same_instance(self):
        a = get_drive_connect_limiter()
        b = get_drive_connect_limiter()
        assert a is b

    def test_default_limit_is_generous_enough_for_humans(self):
        rl = get_drive_connect_limiter()
        # Sanity-check defaults match the docstring contract
        # (10 requests / hour). Keep test in sync if RFC changes.
        assert rl.limit == 10
        assert rl.window_s == 3600.0
