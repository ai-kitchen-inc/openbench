"""Per-request scope: storage, agent, engine resolved against a user.

The Phase-2 wiring built ONE storage backend + ONE agent + ONE
ChatEngine for the whole process. That model breaks down once users
sign in — each user needs their own Drive (or isolated local) storage.
This module is the glue: FastAPI dependencies that resolve the right
backend + agent + engine for the current request, plus a tiny TTL
cache so heavy agent builds don't rerun on every turn.

See ``.tmp/RFC-AUTH-LAYER.md`` §7 — "Per-Request Backend Wiring".
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, HTTPException, status

from lci_mini.auth.dependencies import verify_firebase_token
from lci_mini.auth.drive import get_token_store

if TYPE_CHECKING:
    from openbench import StorageBackend
    from openbench.chat.stores.sqlite import SQLiteSessionStore
    from openbench.integrations.firebase_auth import DriveToken, FirebaseUser
    from openbench.intelligence import BaseAgent


logger = logging.getLogger(__name__)

__all__ = [
    "AGENT_CACHE_TTL",
    "UserAgentCache",
    "_build_agent_for_user",
    "build_engine",
    "local_backend_for_uid",
    "per_user_local_root",
    "reset_agent_cache",
    "resolve_agent",
    "resolve_session_for_thread",
    "resolve_storage_backend",
    "storage_signature",
]


# How long a cached BaseAgent is reused before being rebuilt. Five
# minutes balances "don't keep rebuilding skills on every turn" with
# "pick up persona / skill edits reasonably quickly during iteration".
AGENT_CACHE_TTL = 300.0

# Shared render-items queues stashed from app.py at startup so
# per-request engines can attach the same callbacks without each
# request re-resolving them.
_render_items_fn: Any = None
_clear_render_items_fn: Any = None


def configure_render_queue(render_items_fn: Any, clear_render_items_fn: Any) -> None:
    """Called once from ``create_app`` so per-request engines see the shared queue."""
    global _render_items_fn, _clear_render_items_fn
    _render_items_fn = render_items_fn
    _clear_render_items_fn = clear_render_items_fn


# ---------------------------------------------------------------------------
# Storage — resolve the right StorageBackend for this user
# ---------------------------------------------------------------------------


def per_user_local_root(uid: str) -> Path:
    """Return the local-storage root for a user.

    Layout depends on the active auth mode (:class:`AuthConfig`):

    - ``firebase``: sharded by uid prefix —
      ``<root>/users/<ab>/<uid>/`` keeps the filesystem sane once real
      users arrive. Sanitizes uids that contain path-unsafe characters.
    - ``disabled`` / ``none`` (single-tenant dev / no-auth): flat
      ``<root>/`` layout. Phase-2 deployments and existing tests stay
      compatible.

    Where ``<root>`` is ``LCI_MINI_STORAGE_ROOT`` if set, else
    ``examples/lci-mini/.openbench/``.
    """
    from lci_mini.auth.config import AuthConfig

    base = os.environ.get("LCI_MINI_STORAGE_ROOT")
    if base:
        root = Path(base)
    else:
        from lci_mini.agent import get_persona_dir

        root = get_persona_dir().parent / ".openbench"
    if AuthConfig.from_env().mode != "firebase":
        return root
    safe = _sanitize_uid_component(uid)
    prefix = safe[:2] if len(safe) >= 2 else safe or "_"
    return root / "users" / prefix / safe


def _sanitize_uid_component(uid: str) -> str:
    """Keep uid safe for filesystem use — hash anything suspicious."""
    if not uid:
        return "_"
    if all(c.isalnum() or c in "-_" for c in uid):
        return uid
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:32]


def local_backend_for_uid(uid: str) -> StorageBackend:
    """Build a :class:`LocalStorageBackend` rooted at the user's private dir."""
    from openbench import LocalStorageBackend

    return LocalStorageBackend(per_user_local_root(uid))


def storage_signature(token: DriveToken | None) -> str:
    """Stable identifier for the storage backend a user currently has.

    The signature changes whenever a user connects, disconnects, or
    reconnects Drive (the folder id or the refresh token rotates).
    Cache keys include this signature so :class:`UserAgentCache`
    invalidates automatically on backend transitions.
    """
    if token is None:
        return "local"
    # Hash the folder id + a fragment of the refresh token so a
    # reconnect (new refresh token) invalidates the cache.
    fp_input = f"{token.openbench_folder_id or ''}|{token.refresh_token[:16]}"
    fp = hashlib.sha256(fp_input.encode("utf-8")).hexdigest()[:16]
    return f"drive:{fp}"


def _shared_service_account_backend() -> StorageBackend | None:
    """Return the legacy shared-folder Drive backend if env vars are set.

    Preserves the Phase-2 "all users share one Drive folder owned by a
    service account" deployment path. When both
    ``LCI_MINI_DRIVE_ROOT`` and ``LCI_MINI_SERVICE_ACCOUNT`` are set,
    every request gets this backend regardless of Firebase identity.
    """
    drive_root = os.environ.get("LCI_MINI_DRIVE_ROOT")
    service_account = os.environ.get("LCI_MINI_SERVICE_ACCOUNT")
    if not drive_root:
        return None
    if not service_account:
        raise RuntimeError(
            "LCI_MINI_DRIVE_ROOT is set but LCI_MINI_SERVICE_ACCOUNT is not. "
            "Provide a service-account JSON path or unset LCI_MINI_DRIVE_ROOT."
        )
    from openbench.integrations.gdrive import GoogleDriveStorageBackend

    return GoogleDriveStorageBackend(
        root_folder_id=drive_root,
        service_account_file=service_account,
    )


def resolve_storage_backend(
    user: FirebaseUser = Depends(verify_firebase_token),
) -> StorageBackend:
    """FastAPI dependency — returns the user's StorageBackend.

    Selection rules (first match wins):

    1. If ``LCI_MINI_DRIVE_ROOT`` + ``LCI_MINI_SERVICE_ACCOUNT`` are set,
       return the shared service-account backend for every caller
       (legacy Phase-2 mode — no multi-tenancy).
    2. If the user has a :class:`DriveToken` in :func:`get_token_store`,
       build a per-user :class:`GoogleDriveStorageBackend` with their
       refresh token.
    3. Otherwise, return a per-user :class:`LocalStorageBackend` under
       ``<root>/users/<prefix>/<uid>/``.
    """
    shared = _shared_service_account_backend()
    if shared is not None:
        return shared
    token = _load_drive_token(user.uid)
    if token is None:
        return local_backend_for_uid(user.uid)
    try:
        return _build_drive_backend(token)
    except ImportError as exc:
        logger.warning(
            "gdrive extras missing, falling back to local storage for uid=%s: %s",
            user.uid,
            exc,
        )
        return local_backend_for_uid(user.uid)
    except Exception:  # pragma: no cover — defensive
        logger.exception("Drive backend construction failed for uid=%s", user.uid)
        # Do NOT leak internal errors to the caller; fall back silently.
        return local_backend_for_uid(user.uid)


def _load_drive_token(uid: str) -> DriveToken | None:
    try:
        return get_token_store().load(uid)
    except ImportError as exc:
        # Token store requires firebase / cryptography deps that aren't
        # installed. Treat as "no connection" rather than breaking chat.
        logger.debug("token_store unavailable: %s", exc)
        return None
    except Exception as exc:
        logger.warning("token_store.load failed for uid=%s: %s", uid, exc)
        return None


def _build_drive_backend(token: DriveToken) -> StorageBackend:
    from openbench.integrations.firebase_auth import build_credentials
    from openbench.integrations.gdrive import GoogleDriveStorageBackend

    assert token.openbench_folder_id is not None
    credentials = build_credentials(
        # The access_token will be refreshed lazily by google-auth when
        # the first Drive API call sees it expired.
        access_token="",
        refresh_token=token.refresh_token,
        client_id=token.client_id,
        client_secret=token.client_secret,
        scopes=list(token.scopes),
        token_uri=token.token_uri,
    )
    return GoogleDriveStorageBackend(
        root_folder_id=token.openbench_folder_id,
        credentials=credentials,
    )


# ---------------------------------------------------------------------------
# Agent cache + resolver
# ---------------------------------------------------------------------------


class UserAgentCache:
    """Thread-safe TTL cache keyed by ``(uid, storage_signature)``.

    Two users share no state. The same user reusing the same backend
    within :data:`AGENT_CACHE_TTL` seconds shares the same agent
    instance — avoids rebuilding skills + persona on every turn.
    """

    def __init__(self, ttl: float = AGENT_CACHE_TTL):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], tuple[BaseAgent, float]] = {}

    def get_or_build(
        self,
        uid: str,
        signature: str,
        build_fn: Any,
    ) -> BaseAgent:
        """Return the cached agent for ``(uid, signature)`` or build a new one."""
        key = (uid, signature)
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                agent, expires_at = entry
                if now < expires_at:
                    return agent
                # Expired — fall through to rebuild.
            # Drop any stale entries for this uid whose signature changed
            # so memory doesn't bloat when users toggle Drive frequently.
            stale = [k for k in self._cache if k[0] == uid and k != key]
            for k in stale:
                self._cache.pop(k, None)

        # Build outside the lock — agent construction may be slow and
        # we don't want to serialize distinct users on one another.
        agent = build_fn()
        with self._lock:
            self._cache[key] = (agent, time.monotonic() + self._ttl)
        return agent

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_agent_cache = UserAgentCache()


def reset_agent_cache() -> None:
    """Drop every cached agent. Tests call this between cases."""
    _agent_cache.clear()


def _build_agent_for_user(storage: StorageBackend) -> BaseAgent:
    """Build a BaseAgent wired to the user's scratchpad."""
    from lci_mini.agent import create_lici_agent

    scratchpad = storage.scratchpad_store()
    return create_lici_agent(scratchpad=scratchpad)


def resolve_agent(
    user: FirebaseUser = Depends(verify_firebase_token),
    storage: StorageBackend = Depends(resolve_storage_backend),
) -> BaseAgent:
    """FastAPI dependency — returns the agent for this user + backend.

    Cache key: ``(user.uid, storage_signature(token))``. Reconnect /
    disconnect flows rotate the signature automatically.
    """
    token = _load_drive_token(user.uid)
    signature = storage_signature(token)
    return _agent_cache.get_or_build(
        uid=user.uid,
        signature=signature,
        build_fn=lambda: _build_agent_for_user(storage),
    )


# ---------------------------------------------------------------------------
# Engine + session helpers
# ---------------------------------------------------------------------------


def resolve_session_for_thread(
    thread_id: str | None,
    session_store: SQLiteSessionStore | Any | None,
) -> Any:
    """Load the ChatSession identified by ``thread_id``, or create a new one.

    Required so per-request :class:`ChatEngine` construction preserves
    history across turns — without this, every request would overwrite
    the stored session with just its own turn.
    """
    from openbench.chat import ChatSession

    if thread_id and session_store is not None:
        try:
            loaded = session_store.load(thread_id)
        except Exception as exc:
            logger.warning("session_store.load failed for %s: %s", thread_id, exc)
            loaded = None
        if loaded is not None:
            return loaded
        # thread_id provided but nothing in store yet → create with that id
        return ChatSession(session_id=thread_id)
    return ChatSession()


def build_engine(
    agent: BaseAgent,
    session: Any,
    session_store: Any | None,
) -> Any:
    """Assemble a :class:`ChatEngine` with the shared render callbacks."""
    from openbench.chat import ChatEngine

    return ChatEngine(
        agent=agent,
        session=session,
        session_store=session_store,
        render_items_fn=_render_items_fn,
        clear_render_items_fn=_clear_render_items_fn,
    )


# ---------------------------------------------------------------------------
# Guarded dependency for endpoints that should require Firebase auth
# ---------------------------------------------------------------------------


def require_firebase_user(
    user: FirebaseUser = Depends(verify_firebase_token),
) -> FirebaseUser:
    """Reject anonymous users on endpoints that require a real signed-in identity.

    Accepts ``dev`` (dev bypass) and any real Firebase uid; rejects
    ``anonymous`` (the ``none`` mode synthetic). Use on endpoints that
    read/write per-user storage so legacy deployments without Firebase
    Auth see a clear 401 instead of silently leaking data across
    callers.
    """
    if user.uid == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This endpoint requires Firebase Auth. Set FIREBASE_PROJECT_ID or "
            "OPENBENCH_AUTH_DISABLED=1.",
        )
    return user
