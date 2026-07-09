"""AG-UI protocol transport handler (assembled from transport mixins).

AG-UI handles transport; A2UI handles rendering. Each sessionId gets its own
ChatSession and each request a fresh agent copy, so parallel requests stay
isolated. ag-ui-protocol and fastapi are optional deps, imported lazily.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any

from openbench.chat.transport.agui.content import _ContentExtractionMixin
from openbench.chat.transport.agui.session import _SessionLifecycleMixin
from openbench.chat.transport.agui.streaming import _EventStreamMixin
from openbench.chat.transport.validation import (
    ChatTransportValidationError,
    raise_invalid_request,
    validate_stream_request_body,
)
from openbench.intelligence.base import AgentMemory, BaseAgent

if TYPE_CHECKING:
    import asyncio

    from openbench.chat.session import ChatSession
    from openbench.mcp.permissions import MCPPermissionContext

logger = logging.getLogger(__name__)


class AGUIHandler(_SessionLifecycleMixin, _EventStreamMixin, _ContentExtractionMixin):
    """AG-UI protocol handler for chat message streaming.

    Streams AG-UI events as SSE, wrapping A2UI v0.10 messages inside
    CustomEvent(name="a2ui") payloads. Supports parallel request isolation:
    each sessionId maps to its own ChatSession and each request gets a fresh
    agent copy with clean memory.
    """

    def __init__(self, engine: Any):
        """Initialize AG-UI handler.

        Args:
            engine: ChatEngine instance for processing messages.
        """
        self.engine = engine
        self._sessions: dict[str, ChatSession] = {}
        self._sessions_lock = threading.Lock()

    def _create_request_agent(self) -> Any:
        """Create a request-scoped copy of the agent with fresh memory.

        For BaseAgent: shallow copy with a new AgentMemory (system prompt only).
        For other agent types: returns the original (assumed stateless).
        """
        agent = self.engine.agent
        if isinstance(agent, BaseAgent):
            agent_copy = copy.copy(agent)
            agent_copy.memory = AgentMemory()
            agent_copy.memory.add_system(agent._system_prompt)
            # Share LLM provider and tools (thread-safe, read-only references)
            agent_copy._llm = agent._llm
            agent_copy.tools = agent.tools
            return agent_copy
        return agent

    def _create_permission_context(
        self,
        *,
        session_id: str,
        thread_id: str,
        run_id: str,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> MCPPermissionContext | None:
        """Return an optional MCP permission context for this run."""
        return None

    def _after_user_message(self, session: ChatSession, content: str) -> None:
        """Hook for apps that need to update session metadata after input."""
        return None

    async def handle(self, request: Any) -> Any:
        """Handle an incoming request and return an SSE StreamingResponse.

        Accepts both AG-UI RunAgentInput format and OpenBench format.

        Args:
            request: FastAPI Request object.

        Returns:
            StreamingResponse with AG-UI SSE events.
        """
        from fastapi.responses import StreamingResponse

        try:
            body = validate_stream_request_body(await request.json())
        except (ChatTransportValidationError, ValueError):
            raise_invalid_request()
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
