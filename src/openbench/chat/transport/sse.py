"""
SSE (Server-Sent Events) transport for chat.

FastAPI-compatible endpoint that streams A2UI v0.10 JSONL as SSE events.
More reliable than WebSocket for progressive streaming since HTTP chunked
transfer encoding sends each event immediately.

Note: fastapi is an optional dependency -- imported lazily.
"""
from __future__ import annotations


import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class ChatSSEHandler:
    """FastAPI-compatible SSE handler for chat message streaming.

    Streams A2UI v0.10 JSONL messages as Server-Sent Events. Each message
    is sent as a separate SSE `data:` event, ensuring progressive delivery.

    Usage with FastAPI:
        from fastapi import FastAPI, Request
        from fastapi.responses import StreamingResponse
        from openbench.chat import ChatEngine
        from openbench.chat.transport.sse import ChatSSEHandler

        app = FastAPI()
        engine = ChatEngine(agent=my_agent)
        sse_handler = ChatSSEHandler(engine=engine)

        @app.post("/chat/stream")
        async def chat_stream(request: Request):
            body = await request.json()
            return StreamingResponse(
                sse_handler.stream(body),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
    """

    def __init__(self, engine: Any):
        """Initialize SSE handler.

        Args:
            engine: ChatEngine instance for processing messages.
        """
        self.engine = engine

    async def stream(self, data: dict[str, Any]) -> AsyncIterator[str]:
        """Stream response as SSE events.

        Uses ChatEngine.async_stream() to run the blocking agent call
        in a thread pool while yielding SSE events progressively.

        Args:
            data: Input data dict with "content", optional "sessionId", "attachments".

        Yields:
            SSE-formatted strings: "data: {json}\n\n"
        """
        input_data: dict[str, Any] = {
            "content": data.get("content", ""),
            "session_id": data.get("sessionId"),
            "attachments": data.get("attachments"),
        }

        async for line in self.engine.async_stream(input_data):
            yield f"data: {line}\n\n"
