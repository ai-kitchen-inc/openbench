"""AG-UI SSE event streaming: the queue-bridged agent run loop."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from openbench.chat.transport.agui.messages import A2UIStreamMessage
from openbench.intelligence.base import ProgressEvent
from openbench.mcp.permissions import MCPPermissionContext, use_mcp_permission_context

if TYPE_CHECKING:
    from openbench.chat.session import ChatSession

logger = logging.getLogger(__name__)


class _EventStreamMixin:
    """Mixin for AGUIHandler; not instantiated directly."""

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
            queue: asyncio.Queue[str | ProgressEvent | A2UIStreamMessage | None] = asyncio.Queue()
            loop = asyncio.get_event_loop()

            def on_chunk(delta: str) -> None:
                """Callback from sync agent thread → async queue."""
                loop.call_soon_threadsafe(queue.put_nowait, delta)

            def on_progress(event: ProgressEvent) -> None:
                """Callback from sync agent thread → async queue."""
                loop.call_soon_threadsafe(queue.put_nowait, event)

            permission_context = self._create_permission_context(
                session_id=session_id,
                thread_id=thread_id,
                run_id=run_id,
                queue=queue,
                loop=loop,
            )

            # Clear render items before agent execution
            if self.engine._clear_render_items_fn:
                self.engine._clear_render_items_fn()

            # Run agent in thread pool with per-request agent and session
            agent_task = asyncio.create_task(
                asyncio.to_thread(
                    self._execute_agent_with_permission_context,
                    permission_context,
                    content,
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
                if isinstance(item, A2UIStreamMessage):
                    yield encoder.encode(CustomEvent(name="a2ui", value=item.message))
                    continue
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
            surface_record = None

            if extra_items:
                yield encoder.encode(StepStartedEvent(step_name="Rendering response"))

                # Render only extra_items — skip text to avoid duplication
                components, data_model = self.engine._render_content(None, extra_items)
                components = self.engine._ensure_root(components)
                surface_id = f"s-{uuid.uuid4().hex[:8]}"
                messages = self.engine.builder.build_surface(
                    surface_id, components, data_model=data_model
                )
                # Persist the full snapshot (not just the id) so reloading
                # the session can replay this surface.
                surface_record = self.engine._build_surface_record(
                    surface_id, components, data_model
                )

                for msg in messages:
                    yield encoder.encode(CustomEvent(name="a2ui", value=msg))

                yield encoder.encode(StepFinishedEvent(step_name="Rendering response"))

            # Session history (per-session, not shared)
            text_content = self.engine._extract_text_content(agent_output)
            session.add_assistant_message(
                content=text_content,
                surfaces=[surface_record] if surface_record else None,
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
            # Drop a placeholder assistant message into the session before
            # emitting the error event. Otherwise the reloaded thread
            # ends on a dangling user turn, which looks to the user like
            # their message disappeared. The engine owns the placeholder
            # helper so the behaviour matches ChatEngine.invoke/stream.
            try:
                self.engine._write_aborted_placeholder(session, e)
            except Exception:
                logger.exception(
                    "Failed to write aborted-turn placeholder for session_id=%s",
                    session.session_id,
                )
            yield encoder.encode(RunErrorEvent(message=str(e), code="AGENT_ERROR"))

    def _execute_agent_with_permission_context(
        self,
        permission_context: MCPPermissionContext | None,
        content: str,
        attachments: list | None,
        on_chunk,
        session: ChatSession,
        request_agent: Any,
        on_progress,
    ) -> Any:
        with use_mcp_permission_context(permission_context):
            return self.engine._execute_agent(
                content,
                None,
                attachments,
                on_chunk,
                session,
                request_agent,
                on_progress,
            )
