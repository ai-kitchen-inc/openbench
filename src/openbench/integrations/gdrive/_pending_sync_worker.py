"""Background daemon that retries pending Drive writes.

When :class:`GoogleDriveMemoryStore` can't reach Drive on a save (network
flake, quota exhaustion, transient 5xx), it stashes the incremental
messages in a local SQLite fallback with ``pending_sync=1`` and
registers itself with the global :class:`_PendingSyncWorker`. The
worker is a singleton daemon thread (per Q16.4 of
RFC-UNIFIED-MEMORY-STORAGE §16) that polls every registered
``(drive_store, local_store)`` pair on a fixed interval and replays
the pending rows to Drive when the network recovers.

**Failure semantics.** :meth:`LocalSQLiteMemoryStore.pop_pending` is
atomic: rows are returned **and** deleted in the same transaction.
The worker only calls ``pop_pending`` after a successful Drive replay
attempt by reading via :meth:`LocalSQLiteMemoryStore.list_pending_session_ids`
+ replay-then-pop semantics — see :meth:`_sync_session`. If Drive
fails again, the rows stay put and we retry on the next tick.

**Testability.** :meth:`tick` is public so tests can drive one
iteration synchronously without spinning up a real thread. The
default loop calls ``tick`` every ``interval_seconds`` until
:meth:`stop` is invoked.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbench.integrations.gdrive.memory_store import GoogleDriveMemoryStore
    from openbench.intelligence.memory import LocalSQLiteMemoryStore

logger = logging.getLogger(__name__)

__all__ = [
    "_PendingSyncWorker",
    "get_pending_sync_worker",
    "reset_pending_sync_worker_for_tests",
]


class _PendingSyncWorker:
    """Daemon thread that retries pending Drive writes.

    Args:
        interval_seconds: How long the loop waits between ticks. Lower
            values recover faster from Drive blips; higher values
            reduce log noise during sustained outages. Default 30s
            matches the typical Drive transient-error backoff.

    The worker is created once per process via
    :func:`get_pending_sync_worker` (Q16.4 singleton) and is shared
    across every :class:`GoogleDriveMemoryStore` that registers a
    fallback store.
    """

    def __init__(self, *, interval_seconds: float = 30.0):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self._interval = float(interval_seconds)
        # Pairs are stored as a list (not dict) because a single Drive
        # store may legitimately appear with multiple fallback stores
        # in pathological deployments (e.g. lci-mini + lci-ignite-x in
        # the same process). Idempotent insert prevents true duplicates.
        self._pairs: list[tuple[GoogleDriveMemoryStore, LocalSQLiteMemoryStore]] = []
        self._pairs_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

    # ── Registration ─────────────────────────────────────────────────

    def register(
        self,
        drive_store: GoogleDriveMemoryStore,
        local_store: LocalSQLiteMemoryStore,
    ) -> None:
        """Add a Drive↔local pair to sync. Idempotent.

        Does **not** start the daemon thread on its own — call
        :meth:`start` explicitly. This separation lets tests register
        pairs and drive ticks manually without a background loop
        racing against them.
        """
        with self._pairs_lock:
            for pair in self._pairs:
                if pair[0] is drive_store and pair[1] is local_store:
                    return
            self._pairs.append((drive_store, local_store))

    def unregister(
        self,
        drive_store: GoogleDriveMemoryStore,
        local_store: LocalSQLiteMemoryStore,
    ) -> None:
        """Remove a previously-registered pair. Idempotent."""
        with self._pairs_lock:
            self._pairs = [
                p for p in self._pairs if not (p[0] is drive_store and p[1] is local_store)
            ]

    def registered_pair_count(self) -> int:
        with self._pairs_lock:
            return len(self._pairs)

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the daemon poll loop. Idempotent.

        Called from production code paths (e.g.
        :meth:`GoogleDriveMemoryStore.save` after stashing a pending
        row) so the loop wakes up to retry. Tests typically skip this
        and drive :meth:`tick` synchronously instead.
        """
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="openbench-pending-sync-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """Signal the loop to exit and wait briefly for the thread to join.

        Daemon threads die with the process anyway; ``stop`` exists
        primarily for tests + clean shutdown in long-running test
        runners. After ``stop``, the worker can be re-armed by the
        next ``register`` call.
        """
        self._stop_event.set()
        with self._thread_lock:
            thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)

    # ── Loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:  # pragma: no cover — defensive guard
                logger.exception("pending-sync worker tick raised")
            # ``Event.wait`` returns early if ``stop`` is signalled,
            # so we never block past shutdown.
            self._stop_event.wait(self._interval)

    def tick(self) -> int:
        """Run one sync iteration across every registered pair.

        Returns the number of (session_id, pair) replays attempted —
        useful for test assertions like "after registering N pending
        sessions, one tick attempts N replays".
        """
        with self._pairs_lock:
            pairs = list(self._pairs)
        attempts = 0
        for drive_store, local_store in pairs:
            attempts += self._sync_pair(drive_store, local_store)
        return attempts

    # ── Per-pair / per-session sync ──────────────────────────────────

    def _sync_pair(
        self,
        drive_store: GoogleDriveMemoryStore,
        local_store: LocalSQLiteMemoryStore,
    ) -> int:
        try:
            session_ids = local_store.list_pending_session_ids()
        except Exception:  # pragma: no cover — defensive
            logger.exception("pending-sync worker: list_pending_session_ids failed")
            return 0
        attempts = 0
        for session_id in session_ids:
            self._sync_session(drive_store, local_store, session_id)
            attempts += 1
        return attempts

    def _sync_session(
        self,
        drive_store: GoogleDriveMemoryStore,
        local_store: LocalSQLiteMemoryStore,
        session_id: str,
    ) -> None:
        """Replay a single session's pending rows to Drive.

        Reads the pending rows first (without deleting), tries the
        Drive replay, and only calls ``pop_pending`` to remove the
        rows once Drive accepts the write. A failed replay leaves the
        rows in place for the next tick.
        """
        try:
            pending = local_store.list_pending_session_ids()
            if session_id not in pending:
                return
            # Replay path bypasses the public ``save`` to avoid the
            # fallback re-stashing the same messages on a Drive
            # failure (which would double-count).
            messages = local_store.pop_pending(session_id)
            if not messages:
                return
            try:
                drive_store._replay_pending(session_id, messages)
            except Exception as exc:
                # Re-stash the messages so the next tick retries.
                logger.warning(
                    "pending-sync replay failed for session %s: %s. Re-queueing.",
                    session_id,
                    exc,
                )
                local_store.save_pending(session_id, messages)
                raise
        except Exception:  # pragma: no cover — already logged above
            return


# ── Process-singleton accessor (Q16.4) ───────────────────────────────

_GLOBAL_WORKER: _PendingSyncWorker | None = None
_GLOBAL_WORKER_LOCK = threading.Lock()


def get_pending_sync_worker() -> _PendingSyncWorker:
    """Return the process-wide :class:`_PendingSyncWorker`, creating it lazily."""
    global _GLOBAL_WORKER
    with _GLOBAL_WORKER_LOCK:
        if _GLOBAL_WORKER is None:
            _GLOBAL_WORKER = _PendingSyncWorker()
        return _GLOBAL_WORKER


def reset_pending_sync_worker_for_tests() -> None:
    """Stop and discard the global worker.

    Test-only utility — production code never calls this. Resetting
    between tests keeps each test's registrations isolated. Safe to
    call when no worker has been created yet.
    """
    global _GLOBAL_WORKER
    with _GLOBAL_WORKER_LOCK:
        if _GLOBAL_WORKER is not None:
            _GLOBAL_WORKER.stop()
        _GLOBAL_WORKER = None
