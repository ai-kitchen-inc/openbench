"""Centralized default constants for OpenBench.

Single home for timeouts, batch sizes, and retry counts that were previously
duplicated as bare literals across ``intelligence/``, ``data/stores/``, and
``cli/``. Import the named constant instead of repeating the number so the
default can be tuned in one place.

This module has no internal dependencies — it is safe to import from anywhere
(including ``core/abstractions.py``) without risking an import cycle.
"""

from __future__ import annotations

# --- Timeouts (seconds) ---------------------------------------------------

#: Default per-tool execution timeout when a tool exposes no ``timeout_seconds``.
DEFAULT_TOOL_TIMEOUT_S: float = 30.0

#: Max time to wait for a Pinecone index to become ready.
DEFAULT_INDEX_READY_TIMEOUT_S: int = 60

#: CLI demo: wait for a TCP port to open.
DEFAULT_PORT_WAIT_TIMEOUT_S: int = 15

#: CLI demo: wait for the backend health endpoint.
DEFAULT_HEALTH_WAIT_TIMEOUT_S: int = 30

#: CLI demo: grace period for a subprocess to exit before killing it.
DEFAULT_PROC_WAIT_TIMEOUT_S: int = 5

# --- Batch sizes ----------------------------------------------------------

#: Default embedding batch size for embed/upsert paths.
DEFAULT_EMBED_BATCH_SIZE: int = 100

# --- Retries --------------------------------------------------------------

#: Default max retry attempts for backoff-wrapped external calls.
DEFAULT_MAX_RETRIES: int = 3
