"""
REST handler for A2UI actions (button clicks, form submits).

AG-UI does not define an action mechanism, so this remains a REST POST
endpoint. Receives action data, forwards to ChatEngine, returns A2UI messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AGUIActionHandler:
    """REST handler for A2UI actions.

    Processes button clicks, form submits, and other A2UI events.
    Returns response messages as a JSON array.

    Usage with FastAPI:
        from fastapi import FastAPI, Request
        from openbench.chat import ChatEngine
        from openbench.chat.transport.agui_actions import AGUIActionHandler

        app = FastAPI()
        engine = ChatEngine(agent=my_agent)
        action_handler = AGUIActionHandler(engine=engine)

        @app.post("/chat/action")
        async def chat_action(request: Request):
            return await action_handler.handle(request)
    """

    def __init__(self, engine: Any):
        """Initialize action handler.

        Args:
            engine: ChatEngine instance for processing actions.
        """
        self.engine = engine

    async def handle(self, request: Any) -> list[dict[str, Any]]:
        """Handle an A2UI action and return response messages.

        Args:
            request: FastAPI Request object.

        Returns:
            List of A2UI message dicts.
        """
        body = await request.json()

        action_name = body.get("name")
        surface_id = body.get("surfaceId")
        context = body.get("context", {})

        logger.info(f"Action received: {action_name} on surface {surface_id}")

        input_data = {
            "content": f"[Action: {action_name}]",
            "action": {
                "name": action_name,
                "surfaceId": surface_id,
                "sourceComponentId": body.get("sourceComponentId"),
                "context": context,
            },
        }

        result = await asyncio.to_thread(self.engine.invoke, input_data)
        return result.get("messages", [])
