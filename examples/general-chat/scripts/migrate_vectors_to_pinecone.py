#!/usr/bin/env python
"""Copy existing pgvector chunks into a Pinecone index.

Reads ``openbench_source_chunks`` rows — stored embeddings included, so
nothing is re-embedded — and upserts them through
``PineconeDocumentBackend``. After a run, flipping the admin
``vector_store`` setting to ``pinecone`` serves the same corpus.

Idempotent: upserts by chunk id, so re-running after a partial failure
is cheap and safe. Postgres is never written; rollback is flipping the
setting back.

Usage:
    python examples/general-chat/scripts/migrate_vectors_to_pinecone.py --dry-run
    python examples/general-chat/scripts/migrate_vectors_to_pinecone.py
    python examples/general-chat/scripts/migrate_vectors_to_pinecone.py --owner alice@example.com
    python examples/general-chat/scripts/migrate_vectors_to_pinecone.py --verify 20
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

EXAMPLE_SRC = Path(__file__).resolve().parent.parent / "src"
if str(EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_SRC))

from openbench.data.stores.document_index import (  # noqa: E402
    DEFAULT_CHUNK_TABLE,
    ChunkRow,
    PgVectorBackend,
)
from openbench.data.stores.pinecone_document import (  # noqa: E402
    DEFAULT_PINECONE_DOC_INDEX,
    PineconeDocumentBackend,
)

logger = logging.getLogger("migrate_vectors")

_SELECT_COLUMNS = (
    "chunk_id, source_id, session_id, owner, chunk_index, total_chunks, "
    "content, content_hash, heading, page, sheet, metadata, embedding"
)


def decode_row(db_row: tuple) -> tuple[ChunkRow, list[float]]:
    """Turn a ``SELECT {_SELECT_COLUMNS}`` row into (ChunkRow, vector)."""
    metadata = db_row[11]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    row = ChunkRow(
        chunk_id=db_row[0],
        source_id=db_row[1],
        session_id=db_row[2],
        owner=db_row[3],
        chunk_index=int(db_row[4]),
        total_chunks=int(db_row[5]),
        content=db_row[6],
        content_hash=db_row[7],
        heading=db_row[8],
        page=db_row[9],
        sheet=db_row[10],
        metadata=metadata if isinstance(metadata, dict) else {},
    )
    return row, PgVectorBackend._decode_vector(db_row[12])


def iter_chunk_batches(
    conn: Any, *, owner: str | None, source: str | None, batch_size: int
) -> Iterator[tuple[list[ChunkRow], list[list[float]]]]:
    """Stream (rows, vectors) batches from Postgres via a server-side cursor."""
    clauses = ["embedding IS NOT NULL"]
    params: list[Any] = []
    if owner is not None:
        clauses.append("owner = %s")
        params.append(owner)
    if source is not None:
        clauses.append("source_id = %s")
        params.append(source)
    sql = (
        f"SELECT {_SELECT_COLUMNS} FROM {DEFAULT_CHUNK_TABLE} "
        f"WHERE {' AND '.join(clauses)} ORDER BY source_id, chunk_index"
    )
    with conn.cursor(name="migrate_vectors_to_pinecone") as cursor:
        cursor.itersize = batch_size
        cursor.execute(sql, params)
        rows: list[ChunkRow] = []
        vectors: list[list[float]] = []
        for db_row in cursor:
            row, vector = decode_row(db_row)
            if not vector:
                logger.warning("Skipping %s: stored embedding is empty", row.chunk_id)
                continue
            rows.append(row)
            vectors.append(vector)
            if len(rows) >= batch_size:
                yield rows, vectors
                rows, vectors = [], []
        if rows:
            yield rows, vectors


def migrate_batches(
    backend: PineconeDocumentBackend | None,
    batches: Iterable[tuple[list[ChunkRow], list[list[float]]]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upsert every batch; returns counters and a sample for --verify."""
    migrated = 0
    sources: set[str] = set()
    dimension: int | None = None
    sample: list[tuple[str, str]] = []
    for rows, vectors in batches:
        sources.update(row.source_id for row in rows)
        if len(sample) < 100:
            sample.extend((row.chunk_id, row.content_hash) for row in rows)
        if dimension is None and vectors:
            dimension = len(vectors[0])
            if backend is not None:
                backend.ensure_schema(dimension)
        if backend is not None and not dry_run:
            backend.upsert(rows, vectors)
        migrated += len(rows)
        logger.info(
            "%s %d chunks (%d total)", "would copy" if dry_run else "copied", len(rows), migrated
        )
    return {
        "migrated": migrated,
        "sources": len(sources),
        "dimension": dimension,
        "sample": sample,
    }


def verify_sample(backend: PineconeDocumentBackend, sample: list[tuple[str, str]]) -> int:
    """Spot-check migrated chunks by content hash. Returns mismatch count."""
    failed = 0
    for chunk_id, content_hash in sample:
        chunk = backend.get_chunk(chunk_id)
        if chunk is None or chunk.content_hash != content_hash:
            failed += 1
            logger.error(
                "Verify failed for %s: %s",
                chunk_id,
                "missing in Pinecone" if chunk is None else "content_hash mismatch",
            )
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="count and report without writing")
    parser.add_argument("--owner", help="restrict to one owner key")
    parser.add_argument("--source", help="restrict to one source id")
    parser.add_argument("--batch-size", type=int, default=100, help="chunks per upsert batch")
    parser.add_argument("--index", help="Pinecone index name (default: PINECONE_DOC_INDEX)")
    parser.add_argument("--namespace", help="Pinecone namespace (default: PINECONE_DOC_NAMESPACE)")
    parser.add_argument(
        "--verify", type=int, default=0, metavar="N", help="spot-check N migrated chunks by hash"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    database_url = os.getenv("OPENBENCH_DOC_INDEX_URL") or os.getenv("GENERAL_CHAT_DATABASE_URL")
    if not database_url:
        print("Set OPENBENCH_DOC_INDEX_URL or GENERAL_CHAT_DATABASE_URL first.")
        return 1

    backend: PineconeDocumentBackend | None = None
    if not args.dry_run:
        if not os.getenv("PINECONE_API_KEY"):
            print("Set PINECONE_API_KEY first (or use --dry-run).")
            return 1
        backend = PineconeDocumentBackend(
            index_name=args.index or os.getenv("PINECONE_DOC_INDEX") or DEFAULT_PINECONE_DOC_INDEX,
            namespace=args.namespace or os.getenv("PINECONE_DOC_NAMESPACE") or "",
        )

    try:
        import psycopg
    except ImportError:
        print("This script requires psycopg. Install openbench[gcp].")
        return 1

    with psycopg.connect(database_url) as conn:
        batches = iter_chunk_batches(
            conn, owner=args.owner, source=args.source, batch_size=max(1, args.batch_size)
        )
        result = migrate_batches(backend, batches, dry_run=args.dry_run)

    print(
        f"\n{'would migrate' if args.dry_run else 'migrated'}="
        f"{result['migrated']} sources={result['sources']} dimension={result['dimension']}"
    )
    if result["migrated"] == 0:
        print(
            "WARNING: no chunks were found. If the table is not empty, the "
            "filters or the connection are wrong — do not treat this as done."
        )

    if args.verify and backend is not None and not args.dry_run:
        failed = verify_sample(backend, result["sample"][: args.verify])
        print(f"verified={min(args.verify, len(result['sample']))} failed={failed}")
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
