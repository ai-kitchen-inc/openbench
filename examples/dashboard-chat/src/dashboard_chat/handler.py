"""AG-UI handler with per-user single-conversation semantics.

Dashboard Chat keeps exactly one conversation per user. The handler
enforces that server-side: whatever ``forwardedProps.sessionId`` the
client sends, the stream runs against the canonical ``user-{owner}``
session. Each request gets a shallow agent copy carrying that user's
persistent memory and an owner-scoped toolset, so the shared agent
object stays user-free.
"""

from __future__ import annotations

import copy
import threading
from typing import TYPE_CHECKING, Any

from dashboard_chat.tools import build_toolset

if TYPE_CHECKING:
    from dashboard_chat.connections import ConnectionStore
    from dashboard_chat.dashboards import DashboardStore
from openbench.chat.transport.agui.handler import AGUIHandler
from openbench.chat.transport.validation import (
    ChatTransportValidationError,
    raise_invalid_request,
    validate_stream_request_body,
)
from openbench.intelligence.base import BaseAgent, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore

_SESSION_PREFIX = "user-"


def session_id_for(owner: str) -> str:
    return f"{_SESSION_PREFIX}{owner}"


class DashboardChatHandler(AGUIHandler):
    """AGUIHandler bound to per-owner memory and tools."""

    def __init__(
        self,
        engine: Any,
        memory_store: SQLiteMemoryStore,
        connection_store: ConnectionStore,
        dashboard_store: DashboardStore,
    ):
        super().__init__(engine)
        self._memory_store = memory_store
        self._connection_store = connection_store
        self._dashboard_store = dashboard_store
        self._local = threading.local()

    async def handle_owned(self, request: Any, owner: str) -> Any:
        """Like :meth:`handle`, but pins the stream to ``owner``'s session."""
        from fastapi.responses import StreamingResponse

        try:
            body = validate_stream_request_body(await request.json())
        except (ChatTransportValidationError, ValueError):
            raise_invalid_request()
        forwarded = dict(body.get("forwardedProps") or {})
        forwarded["sessionId"] = session_id_for(owner)
        body["forwardedProps"] = forwarded
        accept = request.headers.get("accept", "text/event-stream")

        return StreamingResponse(
            self._event_stream(body, accept),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    def _on_session_resolved(self, session_id: str) -> None:
        # _event_stream calls this synchronously on the request path right
        # before _create_request_agent — the thread-local carries the id over.
        self._local.session_id = session_id

    def _create_request_agent(self) -> Any:
        agent = self.engine.agent
        if not isinstance(agent, BaseAgent):
            return agent

        session_id = getattr(self._local, "session_id", None) or ""
        owner = session_id.removeprefix(_SESSION_PREFIX) if session_id else "local"

        agent_copy = copy.copy(agent)
        agent_copy.memory = PersistentMemory(store=self._memory_store, session_id=session_id)
        messages = agent_copy.memory.messages
        if not messages or messages[0].role != MessageRole.SYSTEM:
            agent_copy.memory.add_system(agent._system_prompt)
        agent_copy._llm = agent._llm
        agent_copy.tools = build_toolset(owner, self._connection_store, self._dashboard_store)
        return agent_copy
