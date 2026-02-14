"""
WebSocket transport for chat.

FastAPI-compatible WebSocket handler that streams A2UI v0.10 JSONL
to connected clients.

Note: fastapi and websockets are optional dependencies -- imported lazily.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from openbench.chat.a2ui.schema import (
    StepCompleteMessage,
    StepStartMessage,
    StreamMessage,
    StreamMessageType,
)
from openbench.chat.transport.base import ChatTransport

logger = logging.getLogger(__name__)


class ChatWebSocketServer(ChatTransport):
    """FastAPI-compatible WebSocket handler for chat.

    Streams A2UI v0.10 JSONL messages to connected clients and handles
    incoming user messages and actions.

    Usage with FastAPI:
        from fastapi import FastAPI, WebSocket
        from openbench.chat import ChatEngine
        from openbench.chat.transport.websocket import ChatWebSocketServer

        app = FastAPI()
        engine = ChatEngine(agent=my_agent)
        ws_server = ChatWebSocketServer(engine=engine)

        @app.websocket("/chat/ws")
        async def chat_ws(websocket: WebSocket):
            await ws_server.handle(websocket)
    """

    def __init__(self, engine: Any):
        """Initialize WebSocket server.

        Args:
            engine: ChatEngine instance for processing messages.
        """
        # Import here to avoid hard dependency on ChatEngine at module level
        self.engine = engine
        self._sessions: dict[str, str] = {}  # connection_id -> session_id

    async def handle(self, websocket: Any) -> None:
        """Handle a WebSocket connection lifecycle.

        Args:
            websocket: FastAPI WebSocket object.
        """
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        logger.info(f"WebSocket connected: {connection_id}")

        try:
            while True:
                data = await self.receive(websocket)
                msg_type = data.get("type")

                if msg_type == "message":
                    await self._process_message(websocket, data, connection_id)
                elif msg_type == "action":
                    await self._handle_action(websocket, data)
                else:
                    logger.warning(f"Unknown message type: {msg_type}")

        except Exception as e:
            # WebSocketDisconnect or other errors
            logger.info(f"WebSocket disconnected: {connection_id} ({e})")
        finally:
            self._sessions.pop(connection_id, None)

    async def send(self, websocket: Any, data: dict[str, Any]) -> None:
        """Send JSON message to client."""
        await websocket.send_json(data)

    async def receive(self, websocket: Any) -> dict[str, Any]:
        """Receive JSON message from client."""
        text = await websocket.receive_text()
        return json.loads(text)

    async def _send_flush(self, websocket: Any, data: dict[str, Any]) -> None:
        """Send message and yield to event loop to flush the WebSocket frame."""
        await self.send(websocket, data)
        await asyncio.sleep(0)

    async def _process_message(
        self, websocket: Any, data: dict[str, Any], connection_id: str
    ) -> None:
        """Process incoming user message and stream A2UI response with step progress.

        Orchestrates step-by-step streaming directly, running the blocking
        agent call in a thread pool. Each send is followed by an event loop
        yield to ensure WebSocket frames are flushed immediately.
        """
        session_id = data.get("sessionId")

        # Track session
        if session_id:
            self._sessions[connection_id] = session_id

        message_id = f"msg-{uuid.uuid4().hex[:8]}"

        def _step_id() -> str:
            return f"step-{uuid.uuid4().hex[:8]}"

        # Stream start
        await self._send_flush(
            websocket,
            StreamMessage(
                type=StreamMessageType.STREAM_START, message_id=message_id
            ).to_dict(),
        )

        try:
            input_data = {
                "content": data.get("content", ""),
                "attachments": data.get("attachments"),
                "session_id": session_id,
            }

            # ── Step 1: Processing input ──
            sid = _step_id()
            await self._send_flush(
                websocket,
                StepStartMessage(sid, "Processing input", message_id).to_dict(),
            )
            content, attachments = self.engine._parse_input(input_data)
            self.engine.session.add_user_message(content, attachments=attachments)
            await self._send_flush(
                websocket,
                StepCompleteMessage(sid, message_id).to_dict(),
            )

            # ── Step 2: Thinking (in thread pool) ──
            sid = _step_id()
            await self._send_flush(
                websocket,
                StepStartMessage(sid, "Thinking", message_id).to_dict(),
            )
            agent_result = await asyncio.to_thread(
                self.engine._execute_agent, content, None
            )
            agent_output = self.engine._extract_output(agent_result)
            metadata = self.engine._extract_metadata(agent_result)
            await self._send_flush(
                websocket,
                StepCompleteMessage(sid, message_id).to_dict(),
            )

            # ── Step 3: Rendering response ──
            sid = _step_id()
            await self._send_flush(
                websocket,
                StepStartMessage(sid, "Rendering response", message_id).to_dict(),
            )
            components = self.engine._render_content(agent_output)
            components = self.engine._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.engine.builder.build_surface(surface_id, components)

            for msg in messages:
                await self._send_flush(websocket, msg)

            await self._send_flush(
                websocket,
                StepCompleteMessage(sid, message_id).to_dict(),
            )

            # Session history
            text_content = self.engine._extract_text_content(agent_output)
            self.engine.session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}],
                metadata=metadata,
            )

            # Stream end
            await self._send_flush(
                websocket,
                StreamMessage(
                    type=StreamMessageType.STREAM_END,
                    message_id=message_id,
                    metadata=metadata,
                ).to_dict(),
            )

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await self._send_flush(
                websocket,
                StreamMessage(
                    type=StreamMessageType.ERROR,
                    message_id=message_id,
                    metadata={"error": str(e)},
                ).to_dict(),
            )

    async def _handle_action(self, websocket: Any, data: dict[str, Any]) -> None:
        """Handle A2UI action (event dispatched from Button click, etc.).

        Actions are forwarded to the engine for processing. The engine
        may respond with new A2UI messages to update the UI.
        """
        action_name = data.get("name")
        surface_id = data.get("surfaceId")
        context = data.get("context", {})

        logger.info(f"Action received: {action_name} on surface {surface_id}")

        try:
            # Process action through engine as a new message
            input_data = {
                "content": f"[Action: {action_name}]",
                "action": {
                    "name": action_name,
                    "surfaceId": surface_id,
                    "sourceComponentId": data.get("sourceComponentId"),
                    "context": context,
                },
            }
            result = self.engine.invoke(input_data)

            # Stream response
            for msg in result.get("messages", []):
                await self.send(websocket, msg)

        except Exception as e:
            logger.error(f"Error handling action: {e}")
            error_msg = StreamMessage(
                type=StreamMessageType.ERROR,
                message_id=f"action-{uuid.uuid4().hex[:8]}",
                metadata={"error": str(e)},
            )
            await self.send(websocket, error_msg.to_dict())
