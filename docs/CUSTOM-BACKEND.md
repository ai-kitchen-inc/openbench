# Implementing a Custom Storage Backend

OpenBench ships two default storage backends (local filesystem and
Google Drive) that cover the zero-config and multi-device-consumer
paths. Everything else — Postgres, MySQL, Redis, S3, DynamoDB,
Firestore, in-memory for tests, a custom REST service — you implement
yourself. This tutorial walks through that process end-to-end using a
`PostgresMemoryStore` as the running example.

> Storage backends are **plumbing under the Agentic pillar** (see
> [MENTAL_MODEL.md](MENTAL_MODEL.md)). Reach for a Protocol-based
> implementation as shown here, not an MCP server — hot-path latency
> and transactional semantics belong in-process.

---

## When to implement a custom backend

| Your situation | Use |
|---|---|
| Local dev, zero setup | `LocalStorageBackend` (shipped) |
| Consumer app with Google accounts | `GoogleDriveStorageBackend` (shipped) |
| Enterprise with existing Postgres / Redis / S3 | **Custom backend** |
| Compliance requires your own DB for audit | **Custom backend** |
| High-performance agent (Redis memory, Postgres sessions) | **Custom backend** |
| Tests that don't want disk I/O | **Custom backend** (in-memory) |

If you recognize any of the bottom four rows, read on.

---

## The contracts you implement

OpenBench's storage layer is composed of five ABCs + one factory
Protocol:

| ABC | What it stores | Call frequency |
|---|---|---|
| `MemoryStore` | Agent's LLM-internal turn history (tool_calls, tool results) | High — per message write |
| `SessionStore` | UI chat transcript (user + final assistant text) | Medium — per turn |
| `FileStore` | Upload / download files | Low — per user upload |
| `ScratchpadStore` | User-editable markdown memory scratchpad | Very low |
| `PersonaSource` | Agent identity (SOUL/STYLE/AGENTS markdown) | Once per agent build |
| `StorageBackend` (Protocol) | Factory that bundles the five above | Once per request |

Each ABC is stable across minor versions (additive-only signature
changes). You can implement all five, or just the one you need — the
Protocol is duck-typed, so a composite backend that mixes shipped
impls with your custom ones works first-class.

This tutorial focuses on `MemoryStore` because it's the one users
most commonly replace (agent memory is write-heavy, and Postgres /
Redis are natural fits). The same pattern applies to the others.

---

## Step 1 — Implement the ABC

`MemoryStore` requires five abstract methods. Here's a minimal
Postgres implementation:

```python
# my_company/stores/postgres_memory_store.py
from __future__ import annotations

import json
from typing import Any

import psycopg

from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.memory import MemoryStore


class PostgresMemoryStore(MemoryStore):
    """Agent memory persisted in Postgres.

    Uses a single ``openbench_messages`` table with (session_id, ord)
    as the natural key. `ord` is a per-session monotonic counter so
    message order survives concurrent inserts without depending on
    timestamp ordering.
    """

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS openbench_messages (
                    session_id   TEXT    NOT NULL,
                    ord          INTEGER NOT NULL,
                    role         TEXT    NOT NULL,
                    content      TEXT    NOT NULL,
                    name         TEXT,
                    tool_call_id TEXT,
                    tool_calls   JSONB,
                    PRIMARY KEY (session_id, ord)
                )
                """
            )
            self._conn.commit()

    def save(self, session_id: str, messages: list[Message]) -> None:
        if not messages:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(ord), -1) FROM openbench_messages "
                "WHERE session_id = %s",
                (session_id,),
            )
            next_ord = cur.fetchone()[0] + 1
            for i, msg in enumerate(messages):
                cur.execute(
                    """
                    INSERT INTO openbench_messages
                    (session_id, ord, role, content, name, tool_call_id, tool_calls)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        next_ord + i,
                        msg.role.value,
                        msg.content,
                        msg.name,
                        msg.tool_call_id,
                        json.dumps(msg.tool_calls) if msg.tool_calls else None,
                    ),
                )
            self._conn.commit()

    def load(self, session_id: str) -> list[Message]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, name, tool_call_id, tool_calls "
                "FROM openbench_messages WHERE session_id = %s ORDER BY ord",
                (session_id,),
            )
            return [
                Message(
                    role=MessageRole(row[0]),
                    content=row[1],
                    name=row[2],
                    tool_call_id=row[3],
                    tool_calls=row[4],
                )
                for row in cur.fetchall()
            ]

    def search(self, query: str, limit: int = 5) -> list[Message]:
        # Postgres full-text search — an impl can optionally
        # provide this; base class default returns []. Use tsvector
        # indexes in production.
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, name, tool_call_id, tool_calls "
                "FROM openbench_messages "
                "WHERE content ILIKE %s ORDER BY ord DESC LIMIT %s",
                (f"%{query}%", limit),
            )
            return [
                Message(
                    role=MessageRole(row[0]),
                    content=row[1],
                    name=row[2],
                    tool_call_id=row[3],
                    tool_calls=row[4],
                )
                for row in cur.fetchall()
            ]

    def list_sessions(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT session_id FROM openbench_messages"
            )
            return [row[0] for row in cur.fetchall()]

    def delete_session(self, session_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM openbench_messages WHERE session_id = %s",
                (session_id,),
            )
            self._conn.commit()

    def delete_tail(self, session_id: str, count: int) -> None:
        if count <= 0:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM openbench_messages
                WHERE session_id = %s
                  AND ord IN (
                    SELECT ord FROM openbench_messages
                    WHERE session_id = %s
                    ORDER BY ord DESC
                    LIMIT %s
                  )
                """,
                (session_id, session_id, count),
            )
            self._conn.commit()
```

That's 90-ish lines for a production-quality Postgres impl. Other
backends follow the same shape — only the storage primitives change.

---

## Step 2 — Validate against the public contract

OpenBench ships a conformance test suite you inherit to prove your
impl matches the ABC's behavioral contract:

```python
# tests/test_postgres_memory_store.py
import pytest
import psycopg

from openbench.testing import MemoryStoreContract
from my_company.stores import PostgresMemoryStore


@pytest.fixture
def pg_conn():
    conn = psycopg.connect("postgresql://test@localhost/openbench_test")
    yield conn
    conn.close()


class TestPostgresMemoryStore(MemoryStoreContract):
    """Inherits 12 conformance tests from MemoryStoreContract."""

    @pytest.fixture(autouse=True)
    def _setup(self, pg_conn):
        self._conn = pg_conn

    def make_store(self):
        return PostgresMemoryStore(self._conn)

    def cleanup_store(self, store):
        with store._conn.cursor() as cur:
            cur.execute("TRUNCATE openbench_messages")
            store._conn.commit()
```

Run `pytest tests/test_postgres_memory_store.py -v` — you'll get:

```
test_save_load_roundtrip                      PASSED
test_load_unknown_session_returns_empty_list  PASSED
test_save_is_append_not_replace               PASSED
test_delete_session_removes_all_messages      PASSED
test_delete_session_is_idempotent             PASSED
test_delete_unknown_session_does_not_raise    PASSED
test_delete_tail_removes_last_n               PASSED
test_delete_tail_count_exceeding_length_…     PASSED
test_delete_tail_zero_or_negative_is_noop     PASSED
test_list_sessions_returns_known_ids          PASSED
test_preserves_tool_call_fields               PASSED
test_empty_save_is_noop                       PASSED

12 passed
```

Any failure tells you exactly which contract clause your impl misses.
The same test suite runs against OpenBench's own shipped SQLite and
Drive impls — so the bar you meet is identical to the SDK's.

---

## Step 3 — Wire into a StorageBackend

`StorageBackend` is a `@runtime_checkable` `typing.Protocol`. Any
class exposing the five factory methods satisfies it — no inheritance
required. Compose your custom store with shipped impls for the other
data types:

```python
# my_company/backends.py
from openbench.integrations.gdrive import GoogleDriveStorageBackend
from openbench.chat.stores.sqlite import SQLiteSessionStore
from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad
from openbench.intelligence.persona_source import FilesystemPersonaSource
from openbench.chat.files import LocalFileStore

from my_company.stores import PostgresMemoryStore


class EnterpriseBackend:
    """Drive for user-facing data; Postgres for agent memory.

    Layout:
    - session:    Drive (user-owned, cross-device)
    - memory:     Postgres (existing ops infra + audit)
    - files:      Local filesystem (private to each backend instance)
    - scratchpad: Filesystem markdown (co-located with files)
    - persona:    Filesystem (versioned in git)
    """

    def __init__(self, drive_auth, drive_folder_id, pg_conn, base_dir="/var/openbench"):
        self._drive_auth = drive_auth
        self._drive_folder_id = drive_folder_id
        self._pg_conn = pg_conn
        self._base_dir = base_dir

    def session_store(self):
        from openbench.integrations.gdrive.session_store import GoogleDriveSessionStore
        return GoogleDriveSessionStore(
            folder_id=self._drive_folder_id,
            credentials=self._drive_auth,
        )

    def memory_store(self):
        return PostgresMemoryStore(self._pg_conn)   # ← your impl

    def file_store(self):
        return LocalFileStore(upload_dir=f"{self._base_dir}/uploads")

    def output_store(self):
        return LocalFileStore(upload_dir=f"{self._base_dir}/downloads")

    def scratchpad_store(self):
        return LocalMarkdownScratchpad(root=f"{self._base_dir}/scratchpad")

    def persona_source(self, name="default"):
        return FilesystemPersonaSource(f"{self._base_dir}/personas/{name}")
```

Sanity check the Protocol conformance:

```python
from openbench.core.storage import StorageBackend

backend = EnterpriseBackend(drive_auth, folder_id, pg_conn)
assert isinstance(backend, StorageBackend)   # passes — Protocol is duck-typed
```

---

## Step 4 — Resolve per-request

If your app uses per-user backends (common for multi-tenant services),
wire the backend resolution at request scope:

```python
# my_company/app.py
from fastapi import Depends, FastAPI, Request
from my_company.backends import EnterpriseBackend


def resolve_storage(request: Request) -> EnterpriseBackend:
    user = request.state.user              # authenticated user
    drive_auth = load_drive_auth(user)     # your OAuth flow
    pg_conn = get_pg_connection()          # your pool
    return EnterpriseBackend(
        drive_auth=drive_auth,
        drive_folder_id=user.drive_folder,
        pg_conn=pg_conn,
    )


@app.post("/awp")
async def chat_endpoint(
    request: Request,
    storage=Depends(resolve_storage),
):
    from openbench.chat import ChatEngine
    from openbench.intelligence.memory import PersistentMemory
    from openbench.intelligence import BaseAgent

    # Use the backend's stores — consumer code is backend-agnostic
    agent = BaseAgent(...)
    agent.memory = PersistentMemory(
        store=storage.memory_store(),      # Postgres
        session_id=request.state.session_id,
    )
    engine = ChatEngine(
        agent=agent,
        session_store=storage.session_store(),   # Drive
    )
    return await ChatEngine(...).handle(request)
```

`ChatEngine`, `BaseAgent`, `PersistentMemory` — none of them know or
care that memory is in Postgres and sessions are in Drive. They just
call the ABC methods.

---

## Design considerations

### Save semantics

`MemoryStore.save()` is **append**, not replace. `PersistentMemory`
calls it per message outside a turn, or once per turn buffer inside
one. Your impl should not clear the session on save — just add the
given messages to whatever history already exists.

If your underlying storage is blob-shaped (like Drive or S3), you
need to do read-modify-write internally: load the blob, append, write
back. Combined with the per-turn commit from RFC-TOOL-CALL-INTEGRITY
Layer 2a, this pays at most one blob write per agent turn — acceptable
for most deployments.

### Ordering

Messages must load in insertion order. If your storage doesn't
naturally preserve insertion order (e.g., a DynamoDB table without a
sort key), add an explicit monotonic counter like the `ord` column in
the Postgres example.

### Transactionality

`save()` should be atomic at the message-group level — if you're
passed a list of 3 messages, either all land or none do. This matters
because `PersistentMemory.turn()` can pass a multi-message buffer at
commit time; a partial write there would leak back into the orphan
tool_call corruption class the turn transaction exists to prevent.

Most SQL databases give this for free via a single transaction.
Blob-shaped stores (Drive, S3) get it via the atomic overwrite
semantics of their upload API. Distributed KV stores may need extra
care — use their native batch-write primitives.

### Search

`search()` default is no-op. If your backend has native full-text
search (Postgres tsvector, Elasticsearch, OpenSearch), override. If
not, keep the default — a no-op search is a valid contract response.

### Encryption

If your deployment requires encryption at rest, configure it at the
storage layer (Postgres `pgcrypto`, S3 SSE, disk-level encryption).
`Message` content is plaintext at the Python object level — do not
try to encrypt inside the store impl unless you also need to prevent
the backend-side operators from reading content (see OpenBench's
`FirestoreTokenStore` for a reference pattern using AES-GCM).

---

## Distribution

Once your impl passes the contract tests, package it how you like:

| Shape | When |
|---|---|
| Private monorepo module | Internal enterprise use |
| Separate pip package (e.g. `openbench-postgres`) | Public reuse / open source |
| Downstream fork of OpenBench | Don't — the ABC is designed to make this unnecessary |

If your package gains real-world traction (3+ public production
deployments with an active maintainer), it's a candidate for
promotion to an official SDK extra (`openbench[postgres]`). See
RFC-UNIFIED-MEMORY-STORAGE §16 Q8 for the graduation criteria.

---

## Stability guarantees

The `MemoryStore` ABC is part of OpenBench's public API surface:

- **Minor version** (x.Y.z): additive-only changes. New optional
  methods may be added with sensible defaults. Existing signatures
  never change.
- **Major version** (X.y.z): signature changes allowed, with 6-month
  deprecation window announced in the changelog.

Third-party impls are safe to build against this ABC across minor
version bumps. The same guarantee applies to `LLMProvider`,
`DataStore`, `SessionStore`, `FileStore`, `ScratchpadStore`, and
`PersonaSource`.

---

## Further reading

- [RFC-UNIFIED-MEMORY-STORAGE](../.tmp/RFC-UNIFIED-MEMORY-STORAGE.md) —
  full architectural context and rollout plan
- [RFC-STORAGE-LAYER](../.tmp/RFC-STORAGE-LAYER.md) — the Protocol
  pattern this extends
- `src/openbench/testing/memory_store_contract.py` — the 12 tests
  your impl must pass
- `src/openbench/intelligence/memory.py` — the `MemoryStore` ABC
  source of truth
- `src/openbench/core/storage.py` — the `StorageBackend` Protocol
