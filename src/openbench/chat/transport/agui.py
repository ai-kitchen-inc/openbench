"""
AG-UI protocol transport for chat.

Replaces the custom SSE/WebSocket transport with AG-UI (Agent-User Interaction
Protocol) standardized event streaming. Uses AG-UI event types for lifecycle
management and wraps A2UI v0.10 messages as CustomEvent payloads.

AG-UI handles transport; A2UI handles rendering.

Per-session isolation: Each sessionId gets its own ChatSession instance and
each request gets a fresh agent copy (clean memory). This prevents context
contamination when multiple requests stream in parallel.

Note: ag-ui-protocol and fastapi are optional dependencies -- imported lazily.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import uuid
from typing import Any

from openbench.chat.session import ChatSession
from openbench.intelligence.base import AgentMemory, BaseAgent, ProgressEvent

logger = logging.getLogger(__name__)


class AGUIHandler:
    """AG-UI protocol handler for chat message streaming.

    Streams AG-UI events as SSE, wrapping A2UI v0.10 messages inside
    CustomEvent(name="a2ui") payloads.

    Supports parallel request isolation:
    - Each sessionId maps to its own ChatSession (conversation history).
    - Each request gets a fresh agent copy with clean memory.
    - Render items use ContextVar for per-request isolation (no locks needed).

    Event sequence:
        RunStartedEvent
        → StepStartedEvent("Processing input") → StepFinishedEvent
        → StepStartedEvent("Thinking") → StepFinishedEvent
        → StepStartedEvent("Rendering response") → CustomEvent(a2ui)... → StepFinishedEvent
        → RunFinishedEvent

    Usage with FastAPI:
        from fastapi import FastAPI, Request
        from fastapi.responses import StreamingResponse
        from openbench.chat import ChatEngine
        from openbench.chat.transport.agui import AGUIHandler

        app = FastAPI()
        engine = ChatEngine(agent=my_agent)
        handler = AGUIHandler(engine=engine)

        @app.post("/awp")
        async def agent_endpoint(request: Request):
            return await handler.handle(request)
    """

    def __init__(self, engine: Any):
        """Initialize AG-UI handler.

        Args:
            engine: ChatEngine instance for processing messages.
        """
        self.engine = engine
        self._sessions: dict[str, ChatSession] = {}
        self._sessions_lock = threading.Lock()

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

    async def handle(self, request: Any) -> Any:
        """Handle an incoming request and return an SSE StreamingResponse.

        Accepts both AG-UI RunAgentInput format and OpenBench format.

        Args:
            request: FastAPI Request object.

        Returns:
            StreamingResponse with AG-UI SSE events.
        """
        from fastapi.responses import StreamingResponse

        body = await request.json()
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

    async def _event_stream(self, body: dict[str, Any], accept: str) -> Any:
        """Generate AG-UI events as SSE strings.

        Uses an asyncio.Queue bridge to stream text deltas from the sync
        agent thread into async SSE events (TextMessageContent).

        Per-request isolation:
        - Session: looked up/created by forwardedProps.sessionId
        - Agent: fresh copy with clean memory per request
        - Render items: ContextVar per-request isolation

        Args:
            body: Request body (AG-UI RunAgentInput or OpenBench format).
            accept: Accept header for content negotiation.

        Yields:
            SSE-formatted strings.
        """
        from ag_ui.core import (
            CustomEvent,
            RunErrorEvent,
            RunFinishedEvent,
            RunStartedEvent,
            StepFinishedEvent,
            StepStartedEvent,
            TextMessageContentEvent,
            TextMessageEndEvent,
            TextMessageStartEvent,
        )
        from ag_ui.encoder import EventEncoder

        encoder = EventEncoder(accept=accept)

        thread_id = body.get("threadId", f"thread-{uuid.uuid4().hex[:8]}")
        run_id = body.get("runId", f"run-{uuid.uuid4().hex[:8]}")

        # Extract session ID for per-session isolation
        forwarded = body.get("forwardedProps") or {}
        session_id = forwarded.get("sessionId") or thread_id

        # Get or create per-session ChatSession. If the engine has a
        # persistent session store wired, try loading from there first
        # so cross-request / cross-replica history actually carries over
        # (the in-memory dict only survives within a single process).
        session = self._load_session_from_store(session_id)
        if session is None:
            session = self._get_or_create_session(session_id)
        # Give subclasses a hook to run per-request setup (e.g.
        # stashing session_id on a thread-local). Runs regardless of
        # which code path produced ``session`` above.
        self._on_session_resolved(session_id)

        # Create a request-scoped agent copy with fresh memory
        request_agent = self._create_request_agent()

        # Run started
        yield encoder.encode(RunStartedEvent(thread_id=thread_id, run_id=run_id))

        try:
            content, attachments = self._extract_content(body)

            # ── Step 1: Processing input ──
            yield encoder.encode(StepStartedEvent(step_name="Processing input"))
            session.add_user_message(content, attachments=attachments)
            self._persist_session(session)
            yield encoder.encode(StepFinishedEvent(step_name="Processing input"))

            # ── Step 2: Agent execution (with streaming text + progress) ──
            message_id = f"msg-{uuid.uuid4().hex[:8]}"
            queue: asyncio.Queue[str | ProgressEvent | None] = asyncio.Queue()
            loop = asyncio.get_event_loop()

            def on_chunk(delta: str) -> None:
                """Callback from sync agent thread → async queue."""
                loop.call_soon_threadsafe(queue.put_nowait, delta)

            def on_progress(event: ProgressEvent) -> None:
                """Callback from sync agent thread → async queue."""
                loop.call_soon_threadsafe(queue.put_nowait, event)

            # Clear render items before agent execution
            if self.engine._clear_render_items_fn:
                self.engine._clear_render_items_fn()

            # Run agent in thread pool with per-request agent and session
            agent_task = asyncio.create_task(
                asyncio.to_thread(
                    self.engine._execute_agent,
                    content,
                    None,
                    attachments,
                    on_chunk,
                    session,
                    request_agent,
                    on_progress,
                )
            )

            # Signal queue end when agent completes (success or failure)
            def _on_done(fut: asyncio.Future) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, None)

            agent_task.add_done_callback(_on_done)

            # Emit TEXT_MESSAGE_START
            yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))

            # Stream text deltas and progress events as they arrive
            current_step: str | None = None
            any_text_emitted = False

            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, ProgressEvent):
                    # Close previous step, open new one
                    if current_step:
                        yield encoder.encode(StepFinishedEvent(step_name=current_step))
                    current_step = item.phase
                    yield encoder.encode(StepStartedEvent(step_name=current_step))
                else:
                    # Text delta
                    any_text_emitted = True
                    yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=item))

            # Close last sub-step
            if current_step:
                yield encoder.encode(StepFinishedEvent(step_name=current_step))
            elif any_text_emitted:
                # Fallback: no progress events were emitted (non-BaseAgent)
                # Wrap in a single "Thinking" step for backward compatibility
                pass

            # Emit TEXT_MESSAGE_END
            yield encoder.encode(TextMessageEndEvent(message_id=message_id))

            # Get agent result (re-raises if agent errored)
            agent_result = await agent_task

            agent_output = self.engine._extract_output(agent_result)
            metadata = self.engine._extract_metadata(agent_result)

            # Read render items (per-request via ContextVar, no lock needed)
            extra_items = self.engine._render_items_fn() if self.engine._render_items_fn else None

            # ── Step 3: Rendering response (rich content only) ──
            # Text was already streamed via TEXT_MESSAGE events.
            # A2UI surfaces are only for rich content (charts, forms, files).
            surface_id = None

            if extra_items:
                yield encoder.encode(StepStartedEvent(step_name="Rendering response"))

                # Render only extra_items — skip text to avoid duplication
                components, data_model = self.engine._render_content(None, extra_items)
                components = self.engine._ensure_root(components)
                surface_id = f"s-{uuid.uuid4().hex[:8]}"
                messages = self.engine.builder.build_surface(
                    surface_id, components, data_model=data_model
                )

                for msg in messages:
                    yield encoder.encode(CustomEvent(name="a2ui", value=msg))

                yield encoder.encode(StepFinishedEvent(step_name="Rendering response"))

            # Session history (per-session, not shared)
            text_content = self.engine._extract_text_content(agent_output)
            session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}] if surface_id else None,
                metadata=metadata,
            )
            self._persist_session(session)

            # Run finished
            yield encoder.encode(
                RunFinishedEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    result={
                        "content": text_content,
                        "metadata": metadata,
                    },
                )
            )

        except Exception as e:
            logger.error(f"AG-UI stream error: {e}")
            yield encoder.encode(RunErrorEvent(message=str(e), code="AGENT_ERROR"))

    def _extract_content(self, body: dict[str, Any]) -> tuple[str, list | None]:
        """Extract content and attachments from request body.

        Accepts both AG-UI RunAgentInput format (messages array) and
        OpenBench format ({content: "..."}).

        Args:
            body: Request body dict.

        Returns:
            Tuple of (content string, optional attachments list).
        """
        # AG-UI format: messages array with role-based messages
        messages = body.get("messages")
        if messages and isinstance(messages, list):
            # Find the last user message
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    break
            else:
                content = ""

            # Attachments from forwardedProps
            forwarded = body.get("forwardedProps") or {}
            raw_attachments = forwarded.get("attachments")
            attachments = self._coerce_attachments(raw_attachments)
            return content, attachments

        # OpenBench format: {content: "...", attachments: [...]}
        content = body.get("content", "")
        raw_attachments = body.get("attachments")
        attachments = self._coerce_attachments(raw_attachments)
        return content, attachments

    def _coerce_attachments(self, raw: Any) -> list | None:
        """Coerce raw attachment data to Attachment objects or None."""
        if not raw:
            return None
        return self.engine._coerce_attachments(raw) if raw else None
