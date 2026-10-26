"""REST handler for chat session CRUD endpoints.

Exposes list / get / delete operations against a :class:`SessionStore`
so the chat UI's session sidebar can resume prior conversations.

Usage with FastAPI:

    from fastapi import FastAPI, HTTPException
    from openbench.chat.stores.sqlite import SQLiteSessionStore
    from openbench.chat.transport.sessions import AGUISessionHandler

    app = FastAPI()
    store = SQLiteSessionStore(".openbench/sessions.db")
    handler = AGUISessionHandler(session_store=store)

    @app.get("/sessions")
    def list_sessions(limit: int = 50, offset: int = 0):
        return handler.list(limit=limit, offset=offset)

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str):
        session = handler.get(session_id)
        if session is None:
            raise HTTPException(status_code=404)
        return session

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str):
        handler.delete(session_id)
        return {"ok": True}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.chat.session_store import SessionStore


class AGUISessionHandler:
    """REST handler bridging HTTP to a :class:`SessionStore`.

    Attributes:
        session_store: The backing store. If ``None``, all methods
            return empty / default responses so the endpoints can be
            mounted unconditionally.
    """

    def __init__(self, session_store: SessionStore | None = None):
        self.session_store = session_store

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Return session summaries as plain dicts.

        Returns an empty list when no store is configured so the
        frontend can render an empty sidebar instead of erroring.
        """
        if self.session_store is None:
            return []
        return [s.to_dict() for s in self.session_store.list(limit=limit, offset=offset)]

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Return the full session as a dict, or None if absent.

        The caller (e.g. a FastAPI route) is expected to map ``None``
        to an HTTP 404.
        """
        if self.session_store is None:
            return None
        session = self.session_store.load(session_id)
        if session is None:
            return None
        return session.to_dict()

    def delete(self, session_id: str) -> None:
        """Delete a session if the store is configured. Idempotent."""
        if self.session_store is None:
            return
        self.session_store.delete(session_id)

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return matching session summaries (empty if no store)."""
        if self.session_store is None:
            return []
        return [s.to_dict() for s in self.session_store.search(query, limit=limit)]
