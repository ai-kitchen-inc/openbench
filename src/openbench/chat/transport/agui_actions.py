"""
REST handler for A2UI actions (button clicks, form submits).

Handles actions directly with a registry pattern -- no agent re-execution.
Registered handlers process specific action names and return A2UI
updateComponents messages to update surfaces in-place.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openbench.chat.transport.validation import (
    ChatTransportValidationError,
    raise_invalid_request,
    validate_action_request_body,
)

logger = logging.getLogger(__name__)

# Handler type: receives ActionData, returns list of A2UI message dicts
ActionHandler = Callable[["ActionData"], list[dict[str, Any]]]


@dataclass
class ActionData:
    """Parsed action from frontend."""

    name: str
    surface_id: str
    source_component_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    data_model: dict[str, Any] | None = None
    thread_id: str | None = None


class AGUIActionHandler:
    """REST handler for A2UI actions.

    Processes button clicks, form submits, and other A2UI events using
    a handler registry. Registered handlers run directly without agent
    re-execution, returning updateComponents messages to update surfaces.

    Usage with FastAPI:
        from fastapi import FastAPI, Request
        from openbench.chat import ChatEngine
        from openbench.chat.transport.agui_actions import AGUIActionHandler, ActionData

        app = FastAPI()
        engine = ChatEngine(agent=my_agent)
        action_handler = AGUIActionHandler(engine=engine)

        @action_handler.on("submit_form")
        def handle_submit(action: ActionData):
            return [engine.builder.build_update_components(
                action.surface_id,
                [A2UIComponent(id="root", component="Text",
                               properties={"text": "Done!", "variant": "body"})],
            )]

        @app.post("/chat/action")
        async def chat_action(request: Request):
            return await action_handler.handle(request)
    """

    def __init__(self, engine: Any):
        """Initialize action handler.

        Args:
            engine: ChatEngine instance (used for builder access).
        """
        self.engine = engine
        self._handlers: dict[str, ActionHandler] = {}

    def on(self, action_name: str) -> Callable:
        """Decorator to register a handler for a specific action name.

        Args:
            action_name: The action name to handle (e.g. "submit_form").

        Returns:
            Decorator that registers the function.
        """

        def decorator(fn: ActionHandler) -> ActionHandler:
            self._handlers[action_name] = fn
            return fn

        return decorator

    def register(self, action_name: str, handler: ActionHandler) -> None:
        """Register a handler function for a specific action name.

        Args:
            action_name: The action name to handle.
            handler: Callable that receives ActionData and returns A2UI messages.
        """
        self._handlers[action_name] = handler

    async def handle(self, request: Any) -> list[dict[str, Any]]:
        """Handle an A2UI action and return response messages.

        Looks up a registered handler for the action name. If found, calls it.
        Otherwise returns a default confirmation response.

        Args:
            request: FastAPI Request object.

        Returns:
            List of A2UI message dicts.
        """
        try:
            body = validate_action_request_body(await request.json())
        except (ChatTransportValidationError, ValueError):
            raise_invalid_request()

        action = ActionData(
            name=body.get("name", ""),
            surface_id=body.get("surfaceId", ""),
            source_component_id=body.get("sourceComponentId"),
            context=body.get("context", {}),
            data_model=body.get("dataModel"),
            thread_id=body.get("threadId"),
        )

        logger.info("Action received: %s on surface %s", action.name, action.surface_id)

        handler = self._handlers.get(action.name)
        if handler:
            try:
                result = handler(action)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except Exception:
                logger.exception("Handler error for action %s", action.name)
                return self._error_response(action, "Action handler failed")

        return self._default_response(action)

    def get_registered_actions(self) -> list[str]:
        """Return list of registered action names (for schema endpoint)."""
        return list(self._handlers.keys())

    def _default_response(self, action: ActionData) -> list[dict[str, Any]]:
        """Default handler: no-op for unregistered actions.

        Returns an empty list so the surface is NOT modified.
        Only explicitly registered handlers should update surfaces.
        This prevents destructive behavior for data-binding events
        like 'change' from form fields.
        """
        logger.debug("No handler for action %s, ignoring", action.name)
        return []

    def _error_response(self, action: ActionData, message: str) -> list[dict[str, Any]]:
        """Return an A2UI updateComponents with an error callout.

        Includes a root component so the error actually renders.
        Without root, the callout would be orphaned (in Map but not
        in any parent's children list) and never visible.
        """
        return [
            {
                "version": "v0.10",
                "updateComponents": {
                    "surfaceId": action.surface_id,
                    "components": [
                        {
                            "id": "action-error",
                            "component": "ObCallout",
                            "variant": "error",
                            "title": "Error",
                            "message": message,
                        },
                        {
                            "id": "root",
                            "component": "Column",
                            "children": ["action-error"],
                            "gap": "12px",
                        },
                    ],
                },
            }
        ]
