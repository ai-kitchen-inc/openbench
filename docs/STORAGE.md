# Storage Layer

OpenBench separates "what gets stored" from "where it gets stored".
Application code depends on five abstract stores; the runtime picks
the concrete implementation per deployment. This page is the map of
what exists, when to use each, and how to compose them.

> The storage layer is **plumbing under the Agentic pillar**, not a
> pillar of its own — see [MENTAL_MODEL.md](MENTAL_MODEL.md) for why
> persistence stays Protocol-based ABC rather than MCP.

---

## The five stores

| Store | Purpose | Lifecycle | Size profile |
|---|---|---|---|
| `SessionStore` | UI chat transcript (user + final assistant text) | Persistent | Small — per-turn summary |
| `MemoryStore` | LLM-internal turn history (tool_calls, tool responses) | Persistent | Medium — grows per turn |
| `FileStore` | User uploads / agent output files | Persistent | Large — arbitrary file sizes |
| `ScratchpadStore` | User-editable markdown memory (via `memory-scratchpad` skill) | Persistent | Small — handwritten notes |
| `PersonaSource` | Agent identity (SOUL/STYLE/AGENTS markdown) | Usually read-only | Small — kilobytes |

`SessionStore` and `MemoryStore` look similar but serve different
consumers: sessions are what the UI renders in the sidebar, memory is
what the LLM reconstructs conversation from. They share
`session_id` but can use different backends — sessions on Drive for
cross-device UX, memory in Postgres for enterprise audit, for
example.

---

## Shipped implementations

| Store | Local | Cloud |
|---|---|---|
| `SessionStore` | `SQLiteSessionStore` | `GoogleDriveSessionStore` |
| `MemoryStore` | `LocalSQLiteMemoryStore` | *(Phase 2 — coming)* |
| `FileStore` | `LocalFileStore` | `GoogleDriveFileStore` |
| `ScratchpadStore` | `LocalMarkdownScratchpad` | `GoogleDriveScratchpad` |
| `PersonaSource` | `FilesystemPersonaSource` | `GoogleDocPersonaSource`, `GoogleDrivePersonaSource` |

These cover the two most common deployment shapes — zero-config
local dev and multi-device consumer apps. For anything else,
implement your own (see [CUSTOM-BACKEND.md](./CUSTOM-BACKEND.md)).

---

## The `StorageBackend` factory

`StorageBackend` is a `@runtime_checkable typing.Protocol` that
bundles the five stores behind a single factory. It is **not** an
abstract base class — any object exposing the five methods satisfies
the protocol.

```python
from openbench.core.storage import StorageBackend, LocalStorageBackend

backend = LocalStorageBackend("~/.openbench/")
assert isinstance(backend, StorageBackend)      # True

session_store = backend.session_store()
memory_store = backend.memory_store()
# ... etc
```

### Shipped presets

Two presets cover the two shipped deployment shapes:

```python
# Local-only
from openbench import LocalStorageBackend
backend = LocalStorageBackend("~/.openbench/")

# Everything on Drive (per-user OAuth)
from openbench.integrations.gdrive import GoogleDriveStorageBackend
backend = GoogleDriveStorageBackend(
    root_folder_id="1ABC...",
    credentials=oauth_creds,
)
```

### Composing custom backends

The Protocol is duck-typed, so composing a backend that mixes shipped
impls with your own takes a plain class definition — no inheritance:

```python
class MyBackend:
    def session_store(self):    return GoogleDriveSessionStore(...)
    def memory_store(self):     return PostgresMemoryStore(pg_conn)   # custom
    def file_store(self):       return S3FileStore(s3_client)         # custom
    def output_store(self):     return S3FileStore(s3_client)         # custom
    def scratchpad_store(self): return LocalMarkdownScratchpad(...)
    def persona_source(self, name="default"):
        return GitPersonaSource(repo_url, name)                       # custom

from openbench.core.storage import StorageBackend
assert isinstance(MyBackend(), StorageBackend)
```

See [CUSTOM-BACKEND.md](./CUSTOM-BACKEND.md) for the full walkthrough,
including a production-quality `PostgresMemoryStore` reference impl.

---

## Decision matrix

Pick the row that matches your deployment constraint:

| Deployment | Recommended backend |
|---|---|
| Local dev, single user | `LocalStorageBackend("~/.openbench/")` |
| Single-user CLI or desktop app | `LocalStorageBackend` with explicit root |
| Consumer web app, Google login, multi-device | `GoogleDriveStorageBackend` |
| Consumer web app, no Google dependency | `LocalStorageBackend` + per-user root |
| Enterprise, on-prem infra | Custom backend — Postgres/Redis memory, Drive sessions |
| Enterprise, AWS-native | Custom backend — DynamoDB + S3 |
| Compliance-heavy (audit, BAA, HIPAA) | Custom backend — all stores on compliant infra |
| Unit/integration tests | Custom backend — in-memory impls, no I/O |

No single backend is universally correct. The point of the Protocol
is that your choice affects exactly one line (the `resolve_storage`
function) while everything downstream (ChatEngine, BaseAgent,
PersistentMemory) stays the same.

---

## Per-store decision guide

### `MemoryStore` — picking by access pattern

| Access pattern | Natural fit |
|---|---|
| High write frequency, append-heavy | Postgres, MySQL |
| Sub-ms read latency critical | Redis |
| User-owned, cross-device | Google Drive (Phase 2) |
| Zero-config, single instance | SQLite (`LocalSQLiteMemoryStore`) |
| Cloud-native, auto-scaling | DynamoDB, Firestore |
| Compliance, audit | Postgres (with row-level encryption) |

### `SessionStore` — picking by user expectation

| User expectation | Natural fit |
|---|---|
| UI transcript visible from any device | Google Drive |
| Private to this app install | SQLite |
| Centralized admin / audit | Postgres |

### `FileStore` — picking by file workflow

| File workflow | Natural fit |
|---|---|
| Temporary (cleared between sessions) | `LocalFileStore` |
| Persistent user-owned | `GoogleDriveFileStore` |
| Large files, CDN-fronted | S3 + signed URLs |
| Compliance retention | Azure Blob / GCS with lifecycle rules |

---

## Stability guarantees

Each ABC is part of the public API surface with a semver commitment:

- **Minor version**: additive-only changes. Optional methods may be
  added with defaults. Existing signatures never break.
- **Major version**: signature changes allowed, 6-month deprecation
  window announced in changelog.

This applies uniformly to `SessionStore`, `MemoryStore`, `FileStore`,
`ScratchpadStore`, `PersonaSource`, and the `StorageBackend` Protocol
itself. Third-party impls are safe across patch and minor bumps.

---

## Related documentation

- [CUSTOM-BACKEND.md](./CUSTOM-BACKEND.md) — end-to-end tutorial for
  implementing a custom store
- [ARCHITECTURE.md](./ARCHITECTURE.md) — how storage fits into the
  three-layer architecture
- `src/openbench/core/storage.py` — the `StorageBackend` Protocol
  source
- `src/openbench/testing/memory_store_contract.py` — the contract
  test suite for `MemoryStore`
- [RFC-STORAGE-LAYER](../.tmp/RFC-STORAGE-LAYER.md) — foundational
  RFC that introduced the protocol
- [RFC-UNIFIED-MEMORY-STORAGE](../.tmp/RFC-UNIFIED-MEMORY-STORAGE.md)
  — extending the protocol to memory, with the full agnostic
  commitment
