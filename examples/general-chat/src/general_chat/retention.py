"""Session retention sweep.

Deletes sessions whose ``updated_at`` is older than the configured
retention window, replicating the ``DELETE /sessions/{id}`` recipe
(purge source artifacts → clear sources → delete session) and
additionally dropping the LLM-level memory rows, which per-session
deletion leaves behind.

Owners are enumerated from the user store plus the local-dev sentinel —
session stores are owner-scoped and expose no cross-owner listing, so
this stays a zero-core-change sweep. Sessions written under a legacy
empty owner predate multi-tenant mode and are never swept.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from general_chat.server.auth import LOCAL_OWNER

logger = logging.getLogger(__name__)

_PAGE_SIZE = 200


def _expired_session_ids(session_store: Any, cutoff: datetime) -> list[str]:
    """Snapshot expired ids before any deletion (offset drift otherwise)."""
    expired: list[str] = []
    offset = 0
    while True:
        summaries = session_store.list(limit=_PAGE_SIZE, offset=offset)
        if not summaries:
            return expired
        for summary in summaries:
            updated_at = summary.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at < cutoff:
                expired.append(summary.session_id)
        if len(summaries) < _PAGE_SIZE:
            return expired
        offset += _PAGE_SIZE


def run_retention_sweep(
    *,
    retention_days: int,
    user_store: Any,
    session_store_for: Callable[[str], Any],
    sources_for: Callable[[str], Any],
    purge_artifacts: Callable[[list[Any]], None],
    memory_store: Any,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete expired sessions for every known owner.

    Returns ``{"deleted_sessions": n, "owners_scanned": m}``. A failure
    on one session is logged and skipped so a single bad row cannot wedge
    the whole sweep.
    """
    if retention_days <= 0:
        return {"deleted_sessions": 0, "owners_scanned": 0}

    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=retention_days)

    owners = [LOCAL_OWNER]
    owners.extend(record.email for record in user_store.list_users())

    deleted = 0
    for owner in owners:
        session_store = session_store_for(owner)
        sources = sources_for(owner)
        for session_id in _expired_session_ids(session_store, cutoff):
            try:
                purge_artifacts(sources.list(session_id))
                sources.clear(session_id)
                memory_store.delete_session(session_id)
                session_store.delete(session_id)
                deleted += 1
            except Exception:
                logger.exception(
                    "Retention sweep failed for owner=%s session=%s", owner, session_id
                )
    return {"deleted_sessions": deleted, "owners_scanned": len(owners)}
