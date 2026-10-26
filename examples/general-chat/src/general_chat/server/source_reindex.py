"""Background re-embedding of persistent sources.

After the admin switches the embedding model every stored vector was
produced by the previous one and no longer matches new query vectors.
The job walks the shared, group, and agent source threads and re-embeds
each ready source with the active model. One job per process; the admin
UI polls its progress through ``GET /admin/sources/reindex``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from general_chat.source_index import reindex_source_record

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceReindexJob:
    """State of the single in-process reindex job.

    Counters are plain attributes mutated from the running task; the
    event loop is single-threaded so no locking is needed.
    """

    def __init__(self) -> None:
        self.status = "idle"
        self.total = 0
        self.done = 0
        self.ready = 0
        self.failed = 0
        self.skipped = 0
        self.started_at = ""
        self.finished_at = ""
        self.error = ""
        self.embedding_model = ""
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.status == "running"

    def snapshot(self) -> dict[str, Any]:
        """API payload; camelCase to match the rest of the admin surface."""
        return {
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "ready": self.ready,
            "failed": self.failed,
            "skipped": self.skipped,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
            "embeddingModel": self.embedding_model,
        }

    def start(
        self,
        coro_factory: Callable[[], Awaitable[None]],
        *,
        embedding_model: str = "",
    ) -> bool:
        """Begin a run on the current event loop; False when one is in flight."""
        if self.running:
            return False
        self.status = "running"
        self.total = self.done = self.ready = self.failed = self.skipped = 0
        self.started_at = _now()
        self.finished_at = ""
        self.error = ""
        self.embedding_model = embedding_model
        self._task = asyncio.create_task(coro_factory())
        return True

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def record_outcome(self, index_status: str) -> None:
        self.done += 1
        if index_status == "ready":
            self.ready += 1
        elif index_status == "failed":
            self.failed += 1
        else:
            self.skipped += 1

    def finish(self, error: str = "") -> None:
        self.status = "failed" if error else "done"
        self.error = error
        self.finished_at = _now()


async def run_source_reindex(
    job: SourceReindexJob,
    *,
    targets: list[tuple[Any, str]],
    semaphore: asyncio.Semaphore,
    reindex: Callable[[Any], Any] = reindex_source_record,
) -> None:
    """Re-embed every record under ``targets`` and record the outcome on ``job``.

    Args:
        job: The job whose counters and status are updated.
        targets: ``(owner-scoped source store, thread id)`` pairs — one per
            shared/group/agent source collection.
        semaphore: The host's indexing bound, shared with uploads so a
            reindex cannot fan out unbounded embedding batches.
        reindex: The per-record worker; injectable for tests.
    """
    try:
        batches: list[tuple[Any, list[Any]]] = []
        for store, thread in targets:
            records = await asyncio.to_thread(store.list, thread)
            batches.append((store, records))
        job.total = sum(len(records) for _, records in batches)
        for store, records in batches:
            for record in records:
                async with semaphore:
                    record = await asyncio.to_thread(reindex, record)
                await asyncio.to_thread(store.upsert, record)
                job.record_outcome((record.metadata or {}).get("indexStatus", ""))
    except asyncio.CancelledError:
        job.finish("dibatalkan")
        raise
    except Exception as exc:
        logger.exception("Source reindex failed")
        job.finish(str(exc))
        return
    job.finish()


__all__ = ["SourceReindexJob", "run_source_reindex"]
