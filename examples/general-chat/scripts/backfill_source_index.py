#!/usr/bin/env python
"""Backfill the chunk index and Parquet tables for existing sources.

Sources ingested before the index existed have ``record.text`` but no
chunks and no Parquet. Until they are backfilled the read path falls back
to sending their full text, so run this once after enabling
``GENERAL_CHAT_SOURCE_INDEX_ENABLED`` and before switching the prompt to
card mode.

Idempotent: sources whose chunks already match by content hash cost no
embedding calls, so re-running after a partial failure is cheap.

Usage:
    python examples/general-chat/scripts/backfill_source_index.py --dry-run
    python examples/general-chat/scripts/backfill_source_index.py
    python examples/general-chat/scripts/backfill_source_index.py --owner alice@example.com
    python examples/general-chat/scripts/backfill_source_index.py --prune
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

EXAMPLE_SRC = Path(__file__).resolve().parent.parent / "src"
if str(EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_SRC))

from general_chat import source_index  # noqa: E402
from general_chat.sources import build_source_store  # noqa: E402

logger = logging.getLogger("backfill")


def _iter_records(store, *, owner: str | None, session: str | None):
    """Yield every stored SourceRecord matching the filters.

    Works against both the Postgres and the JSON store by going through
    the owner-scoped view each backend exposes.
    """
    owners = [owner] if owner else _known_owners(store)
    for owner_key in owners:
        scoped = store.for_owner(owner_key)
        for session_id in _known_sessions(scoped, session):
            yield from scoped.list(session_id)


def _known_owners(store) -> list[str]:
    for method in ("owners", "list_owners"):
        accessor = getattr(store, method, None)
        if callable(accessor):
            try:
                return list(accessor())
            except Exception:
                pass
    # Fall back to the ownerless view, which covers single-tenant and
    # pre-ownership deployments.
    return [""]


def _known_sessions(scoped_store, session: str | None) -> list[str]:
    if session:
        return [session]
    for method in ("sessions", "list_sessions"):
        accessor = getattr(scoped_store, method, None)
        if callable(accessor):
            try:
                return list(accessor())
            except Exception:
                pass
    return []


def backfill(args: argparse.Namespace) -> int:
    root = source_index.storage_root()
    store = build_source_store(str(root))

    kinds = {kind.strip() for kind in (args.kinds or "").split(",") if kind.strip()}
    indexed = skipped = failed = 0

    for record in _iter_records(store, owner=args.owner, session=args.session):
        if args.limit and indexed >= args.limit:
            break
        if kinds and record.kind not in kinds:
            continue
        if record.status != "ready":
            continue
        metadata = record.metadata or {}
        if metadata.get("indexStatus") == "ready" and not args.force:
            skipped += 1
            continue

        if args.dry_run:
            print(f"would index {record.id}  {record.name}  ({len(record.text):,} chars)")
            indexed += 1
            continue

        updated = source_index.index_source_record(record)
        status = (updated.metadata or {}).get("indexStatus")
        if status == "ready":
            indexed += 1
        elif status == "failed":
            failed += 1
            logger.warning(
                "Failed to index %s: %s", record.id, (updated.metadata or {}).get("indexError")
            )
        else:
            skipped += 1

        if not args.dry_run:
            store.for_owner(record.owner).upsert(updated)

    print(f"\nindexed={indexed} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def prune(args: argparse.Namespace) -> int:
    """Delete chunks and tables whose source no longer exists.

    Covers rows orphaned before the delete routes were wired up, and the
    JSON-store path where deletes happen at file level.
    """
    root = source_index.storage_root()
    store = build_source_store(str(root))

    live = {record.id for record in _iter_records(store, owner=args.owner, session=args.session)}
    index = source_index.get_document_index()
    catalog = source_index.get_table_catalog()
    if index is None and catalog is None:
        print("Nothing to prune: the source index is not enabled.")
        return 0

    orphans: set[str] = set()
    if catalog is not None:
        for artifact in catalog.list_for():
            if artifact.source_id not in live:
                orphans.add(artifact.source_id)

    for source_id in sorted(orphans):
        if args.dry_run:
            print(f"would prune {source_id}")
            continue
        source_index.deindex_source(source_id)
        print(f"pruned {source_id}")

    print(f"\norphans={len(orphans)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--owner", help="restrict to one owner key")
    parser.add_argument("--session", help="restrict to one session id")
    parser.add_argument("--kinds", help="comma-separated source kinds to include")
    parser.add_argument("--limit", type=int, default=0, help="stop after N sources")
    parser.add_argument("--force", action="store_true", help="re-index already-indexed sources")
    parser.add_argument("--prune", action="store_true", help="delete artifacts with no source")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not source_index.source_index_enabled():
        os.environ["GENERAL_CHAT_SOURCE_INDEX_ENABLED"] = "1"
        source_index.reset_caches()
        print("GENERAL_CHAT_SOURCE_INDEX_ENABLED was unset; enabling it for this run.")

    return prune(args) if args.prune else backfill(args)


if __name__ == "__main__":
    raise SystemExit(main())
