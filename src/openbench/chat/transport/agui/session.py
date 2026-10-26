"""Per-session lifecycle helpers for the AG-UI handler."""

from __future__ import annotations

import logging

from openbench.chat.session import ChatSession

logger = logging.getLogger(__name__)


class _SessionLifecycleMixin:
    """Mixin for AGUIHandler; not instantiated directly."""

    def _get_or_create_session(self, session_id: str) -> ChatSession:
        """Get or create a ChatSession for the given session ID.

        Thread-safe: uses a lock for concurrent access.
        """
        with self._sessions_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = ChatSession(session_id=session_id)
            return self._sessions[session_id]

    def _on_session_resolved(self, session_id: str) -> None:
        """Hook fired once per request after ``session`` has been resolved.

        Default: no-op. Subclasses override to stash the id on a
        thread-local for their :meth:`_create_request_agent` override.
        """
        return None

    def _load_session_from_store(self, session_id: str) -> ChatSession | None:
        """Load from the engine's session store if one is wired.

        Returns None when the engine has no store, the session is absent,
        or the load raises (logged and swallowed). Callers fall back to
        the in-memory dict.
        """
        store = getattr(self.engine, "session_store", None)
        if store is None:
            return None
        try:
            loaded = store.load(session_id)
        except Exception:
            logger.exception("session_store.load failed for %s", session_id)
            return None
        if loaded is not None:
            # Cache for next call so we don't hit the store every turn.
            with self._sessions_lock:
                self._sessions[session_id] = loaded
        return loaded

    def _persist_session(self, session: ChatSession) -> None:
        """Save ``session`` to the engine's store, logging full tracebacks."""
        store = getattr(self.engine, "session_store", None)
        if store is None:
            return
        try:
            store.save(session)
            logger.info(
                "session saved: session_id=%s, messages=%d, store=%s",
                session.session_id,
                len(session.messages),
                type(store).__name__,
            )
        except Exception:
            logger.exception("session_store.save failed for session_id=%s", session.session_id)
