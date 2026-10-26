"""Demo-specific auth wiring for lci-mini.

This package is the glue between OpenBench's framework-agnostic
auth primitives (``openbench.integrations.firebase_auth``) and
FastAPI. Projects embedding OpenBench typically copy or fork this
directory rather than import from it.

Currently ships:

- :class:`AuthConfig` — env-var-driven configuration dataclass.
- :func:`verify_firebase_token` — FastAPI dependency that returns a
  :class:`FirebaseUser` (real or synthetic in dev mode).
"""

from __future__ import annotations

from lci_mini.auth.config import AuthConfig
from lci_mini.auth.dependencies import verify_firebase_token

__all__ = [
    "AuthConfig",
    "verify_firebase_token",
]
