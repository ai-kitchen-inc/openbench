"""Refresh logic + the in-process interval scheduler for live dashboards.

``refresh_record`` is pure-ish (store I/O happens in the caller) so it can be
unit-tested with a fake runner; ``LiveDashboardScheduler`` owns the asyncio
loop task started from the API process (the only container with access to the
docker socket the ``db_server`` MCP needs).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from general_chat.live_dashboard.hub import LiveDashboardHub, LiveEvent
from general_chat.live_dashboard.models import LiveDashboardRecord, utc_now_iso
from openbench.output.generators.dashboard.normalizer import normalize_dashboard_view_model

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from general_chat.live_dashboard.runner import LiveQueryRunner

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 500


def compute_data_hash(datasets: dict[str, Any]) -> str:
    """Stable fingerprint of the datasets (order-independent)."""
    encoded = json.dumps(datasets, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def hydrate_view_model(
    record: LiveDashboardRecord, datasets: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Template + fresh datasets -> canonical ViewModel with rows inlined."""
    content: dict[str, Any] = dict(record.template)
    content["title"] = record.title
    content["description"] = record.description
    content["datasets"] = datasets
    view_model = normalize_dashboard_view_model(content, title=record.title)
    view_model["title"] = record.title
    view_model["description"] = record.description
    return view_model


def next_run_at(
    interval_seconds: int,
    now: datetime,
    *,
    jitter_ratio: float = 0.1,
    rand: Callable[[], float] = random.random,
) -> str | None:
    """Next due time with up to ``jitter_ratio`` of the interval added (spreads load)."""
    if interval_seconds <= 0:
        return None
    jitter = interval_seconds * max(0.0, jitter_ratio) * rand()
    return utc_now_iso(now + timedelta(seconds=interval_seconds + jitter))


def select_due(records: Iterable[LiveDashboardRecord], now: datetime) -> list[LiveDashboardRecord]:
    now_iso = utc_now_iso(now)
    return [
        record
        for record in records
        if record.enabled
        and record.refresh_interval_seconds > 0
        and (record.next_run_at is None or record.next_run_at <= now_iso)
    ]


def refresh_record(
    record: LiveDashboardRecord,
    runner: LiveQueryRunner,
    *,
    now: datetime | None = None,
    force: bool = False,
    rand: Callable[[], float] = random.random,
) -> tuple[LiveDashboardRecord, LiveEvent | None]:
    """Run the queries and fold the result into ``record`` (mutated + returned).

    - A failing query keeps that dataset's previous rows and records the error
      under ``snapshot["errors"][key]``.
    - When every query fails nothing changes except ``last_error`` and the
      schedule; an ``error`` event is emitted.
    - Unchanged data (same hash) emits nothing unless ``force`` is set, which
      re-publishes the current snapshot (manual refresh feedback).
    """
    moment = now or datetime.now(timezone.utc)
    now_iso = utc_now_iso(moment)
    outcomes = runner.run_queries(record.server_id, record.queries)

    previous_datasets = record.snapshot.get("datasets")
    datasets: dict[str, list[dict[str, Any]]] = (
        {key: list(rows) for key, rows in previous_datasets.items() if isinstance(rows, list)}
        if isinstance(previous_datasets, dict)
        else {}
    )
    errors: dict[str, str] = {}
    succeeded = 0
    for key, outcome in outcomes.items():
        if outcome.ok:
            datasets[key] = outcome.rows or []
            succeeded += 1
        else:
            errors[key] = (outcome.error or "query returned no rows")[:MAX_ERROR_CHARS]
    # Datasets whose query was removed must not linger in the snapshot.
    for key in list(datasets):
        if key not in record.queries:
            datasets.pop(key)

    record.last_refresh_at = now_iso
    record.next_run_at = next_run_at(record.refresh_interval_seconds, moment, rand=rand)

    if outcomes and succeeded == 0:
        record.last_error = "; ".join(f"{key}: {message}" for key, message in errors.items())[
            :MAX_ERROR_CHARS
        ]
        snapshot = dict(record.snapshot)
        snapshot["errors"] = errors
        record.snapshot = snapshot
        return record, LiveEvent(
            "error",
            {
                "id": record.id,
                "version": record.version,
                "error": record.last_error,
                "errors": errors,
                "refreshedAt": now_iso,
            },
        )

    record.last_error = None
    new_hash = compute_data_hash(datasets)
    changed = new_hash != record.data_hash
    has_view_model = isinstance(record.snapshot.get("viewModel"), dict)
    if not (changed or force or not has_view_model):
        snapshot = dict(record.snapshot)
        snapshot["errors"] = errors
        record.snapshot = snapshot
        return record, None

    view_model = hydrate_view_model(record, datasets)
    if changed:
        record.version += 1
    record.data_hash = new_hash
    record.snapshot = {
        "datasets": datasets,
        "viewModel": view_model,
        "errors": errors,
        "refreshedAt": now_iso,
    }
    return record, LiveEvent("update", record.public_payload())


class LiveDashboardScheduler:
    """Interval scheduler: ticks, finds due dashboards, refreshes them."""

    def __init__(
        self,
        store: Any,
        runner: LiveQueryRunner,
        hub: LiveDashboardHub,
        *,
        tick_seconds: float = 5.0,
        max_concurrent: int = 2,
        now_fn: Callable[[], datetime] | None = None,
    ):
        self._store = store
        self._runner = runner
        self._hub = hub
        self.tick_seconds = max(1.0, float(tick_seconds))
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._locks: dict[str, asyncio.Lock] = {}
        self._inflight: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def inflight(self) -> frozenset[str]:
        return frozenset(self._inflight)

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("live-dashboard scheduler tick failed")

    async def tick(self) -> int:
        """Start a refresh for every due dashboard not already running."""
        now_iso = utc_now_iso(self._now_fn())
        due = await asyncio.to_thread(self._store.list_due, now_iso)
        started = 0
        for record in due:
            if record.id in self._inflight:
                continue
            task = asyncio.create_task(self.refresh(record.id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            started += 1
        return started

    async def refresh(
        self, dashboard_id: str, *, force: bool = False
    ) -> LiveDashboardRecord | None:
        """Refresh one dashboard now; serialized per id, bounded globally.

        Only the refresh-owned fields (snapshot, hash, version, schedule,
        last error) are written back, onto the record as it exists AFTER the
        queries ran: a PATCH, tool edit or delete that landed meanwhile is
        never overwritten or resurrected. If the definition changed in the
        window the stale snapshot is dropped and the record is due again.
        """
        lock = self._locks.setdefault(dashboard_id, asyncio.Lock())
        async with lock:
            self._inflight.add(dashboard_id)
            try:
                async with self._semaphore:
                    record = await asyncio.to_thread(self._store.get, dashboard_id)
                    if record is None:
                        self._locks.pop(dashboard_id, None)
                        return None
                    if not record.enabled and not force:
                        return record
                    now = self._now_fn()
                    try:
                        refreshed, event = await asyncio.to_thread(
                            refresh_record, record, self._runner, now=now, force=force
                        )
                    except Exception as exc:
                        logger.exception("live-dashboard refresh failed id=%s", dashboard_id)
                        refreshed, event = record, None
                        refreshed.last_error = f"refresh failed: {exc}"[:MAX_ERROR_CHARS]
                        refreshed.last_refresh_at = utc_now_iso(now)
                        refreshed.next_run_at = next_run_at(record.refresh_interval_seconds, now)
                    latest = await asyncio.to_thread(self._store.get, dashboard_id)
                    if latest is None:
                        return None  # deleted while the queries ran
                    if latest.queries != record.queries or latest.template != record.template:
                        latest.next_run_at = None  # definition changed: refresh again soon
                        await asyncio.to_thread(self._store.save, latest)
                        return latest
                    latest.snapshot = refreshed.snapshot
                    latest.data_hash = refreshed.data_hash
                    latest.version = refreshed.version
                    latest.last_refresh_at = refreshed.last_refresh_at
                    latest.last_error = refreshed.last_error
                    latest.next_run_at = refreshed.next_run_at
                    await asyncio.to_thread(self._store.save, latest)
                    if event is not None:
                        self._hub.publish(dashboard_id, event)
                    return latest
            finally:
                self._inflight.discard(dashboard_id)
