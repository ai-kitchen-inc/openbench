"""
AG-UI protocol transport for chat.

Replaces the custom SSE/WebSocket transport with AG-UI (Agent-User Interaction
Protocol) standardized event streaming. Uses AG-UI event types for lifecycle
management and wraps A2UI v0.10 messages as CustomEvent payloads.

AG-UI handles transport; A2UI handles rendering.

Note: ag-ui-protocol and fastapi are optional dependencies -- imported lazily.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class AGUIHandler:
    """AG-UI protocol handler for chat message streaming.

    Streams AG-UI events as SSE, wrapping A2UI v0.10 messages inside
    CustomEvent(name="a2ui") payloads.

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
        )
        from ag_ui.encoder import EventEncoder

        encoder = EventEncoder(accept=accept)

        thread_id = body.get("threadId", f"thread-{uuid.uuid4().hex[:8]}")
        run_id = body.get("runId", f"run-{uuid.uuid4().hex[:8]}")

        # Run started
        yield encoder.encode(RunStartedEvent(thread_id=thread_id, run_id=run_id))

        try:
            content, attachments = self._extract_content(body)

            # ── Step 1: Processing input ──
            yield encoder.encode(StepStartedEvent(step_name="Processing input"))
            self.engine.session.add_user_message(content, attachments=attachments)
            yield encoder.encode(StepFinishedEvent(step_name="Processing input"))

            # ── Step 2: Thinking (in thread pool) ──
            yield encoder.encode(StepStartedEvent(step_name="Thinking"))
            agent_result = await asyncio.to_thread(
                self.engine._execute_agent, content, None, attachments
            )
            agent_output = self.engine._extract_output(agent_result)
            metadata = self.engine._extract_metadata(agent_result)
            extra_items = self.engine._render_items_fn() if self.engine._render_items_fn else None
            yield encoder.encode(StepFinishedEvent(step_name="Thinking"))

            # ── Step 3: Rendering response ──
            yield encoder.encode(StepStartedEvent(step_name="Rendering response"))
            components = self.engine._render_content(agent_output, extra_items)
            components = self.engine._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.engine.builder.build_surface(surface_id, components)

            for msg in messages:
                yield encoder.encode(CustomEvent(name="a2ui", value=msg))

            yield encoder.encode(StepFinishedEvent(step_name="Rendering response"))

            # Session history
            text_content = self.engine._extract_text_content(agent_output)
            self.engine.session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}],
                metadata=metadata,
            )

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
