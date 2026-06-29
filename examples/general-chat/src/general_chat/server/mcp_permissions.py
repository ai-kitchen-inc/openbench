"""Inline MCP permission prompts for General Chat."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from openbench.chat.a2ui import A2UIMessageBuilder
from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.transport.agui import A2UIStreamMessage
from openbench.chat.transport.agui_actions import ActionData
from openbench.mcp.permissions import MCPPermissionRequest


@dataclass
class PendingMCPPermission:
    request_id: str
    session_id: str
    surface_id: str
    request: MCPPermissionRequest
    event: threading.Event
    response: str | None = None


class GeneralChatMCPPermissionCoordinator:
    """Coordinates browser approval actions with blocked MCP tool calls."""

    def __init__(self, *, timeout_seconds: float | None = None):
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.getenv("GENERAL_CHAT_MCP_PERMISSION_TIMEOUT_SECONDS", "120"))
        )
        self._builder = A2UIMessageBuilder()
        self._pending: dict[str, PendingMCPPermission] = {}
        self._lock = threading.Lock()
        # session_id -> set of tool names the user chose to "Always allow".
        # Keyed by tool name (not arguments) so every later call of that tool
        # skips the prompt, even though its arguments differ each time.
        self._always_allowed: dict[str, set[str]] = {}

    def request_permission(
        self,
        *,
        session_id: str,
        request: MCPPermissionRequest,
        queue: Any,
        loop: Any,
    ) -> str | None:
        # Session-scoped "Always allow": once approved, skip the prompt for
        # every subsequent call of the same tool in this session.
        with self._lock:
            if request.tool_name in self._always_allowed.get(session_id, set()):
                return "yes"

        request_id = f"mcp-perm-{uuid.uuid4().hex[:12]}"
        surface_id = f"s-{request_id}"
        pending = PendingMCPPermission(
            request_id=request_id,
            session_id=session_id,
            surface_id=surface_id,
            request=request,
            event=threading.Event(),
        )
        with self._lock:
            self._pending[request_id] = pending

        self._emit(queue, loop, self._build_surface(pending, status="pending"))
        try:
            if not pending.event.wait(self.timeout_seconds):
                self._finish_pending(request_id, "timeout")
                self._emit(queue, loop, self._build_update(pending, status="timeout"))
                return None
            return pending.response
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def resolve_action(self, action: ActionData) -> list[dict[str, Any]]:
        context = action.context or {}
        request_id = str(context.get("requestId") or "")
        decision = str(context.get("decision") or "").strip().lower()
        with self._lock:
            pending = self._pending.get(request_id)

        if pending is None:
            return self._error_update(
                action.surface_id,
                "This MCP permission request is no longer pending.",
            )
        if action.thread_id and action.thread_id != pending.session_id:
            return self._error_update(
                pending.surface_id,
                "This MCP permission request belongs to a different chat session.",
            )
        if decision not in {"allow", "deny", "allow_session"}:
            return self._error_update(
                pending.surface_id,
                "Choose Allow, Deny, or Always allow to resolve this MCP permission request.",
            )

        if decision == "allow_session":
            with self._lock:
                self._always_allowed.setdefault(pending.session_id, set()).add(
                    pending.request.tool_name
                )

        pending.response = "no" if decision == "deny" else "yes"
        pending.event.set()
        return self._build_update(
            pending,
            status="denied" if decision == "deny" else "approved",
        )

    def _finish_pending(self, request_id: str, response: str | None) -> None:
        with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return
        pending.response = response
        pending.event.set()

    def _emit(self, queue: Any, loop: Any, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            loop.call_soon_threadsafe(queue.put_nowait, A2UIStreamMessage(message))

    def _build_surface(
        self,
        pending: PendingMCPPermission,
        *,
        status: str,
    ) -> list[dict[str, Any]]:
        return self._builder.build_surface(
            pending.surface_id,
            self._components(pending, status=status),
        )

    def _build_update(
        self,
        pending: PendingMCPPermission,
        *,
        status: str,
    ) -> list[dict[str, Any]]:
        return [
            self._builder.build_update_components(
                pending.surface_id,
                self._components(pending, status=status),
            )
        ]

    def _error_update(self, surface_id: str, message: str) -> list[dict[str, Any]]:
        return [
            self._builder.build_update_components(
                surface_id,
                [
                    A2UIComponent(
                        id="mcp-permission-error",
                        component="ObCallout",
                        properties={
                            "variant": "error",
                            "title": "MCP permission",
                            "content": message,
                        },
                    ),
                    A2UIComponent(
                        id="root",
                        component="Column",
                        properties={
                            "children": ["mcp-permission-error"],
                            "gap": "12px",
                        },
                    ),
                ],
            )
        ]

    def _components(
        self,
        pending: PendingMCPPermission,
        *,
        status: str,
    ) -> list[A2UIComponent]:
        request = pending.request
        title = "MCP tool permission"
        status_text = {
            "pending": "Waiting for your approval before the tool runs.",
            "approved": "Approved. The tool is running now.",
            "denied": "Denied. The tool was not run.",
            "timeout": "Timed out. The tool was not run.",
        }.get(status, "Permission request updated.")
        children = ["mcp-permission-title", "mcp-permission-body"]
        components = [
            A2UIComponent(
                id="mcp-permission-title",
                component="Text",
                properties={"text": title, "variant": "h4"},
            ),
            A2UIComponent(
                id="mcp-permission-body",
                component="ObCallout",
                properties={
                    "variant": "warning" if status == "pending" else "info",
                    "title": status_text,
                    "content": (
                        f"Tool: `{request.tool_name}`\n\n"
                        f"Purpose: {request.purpose or 'No description provided.'}\n\n"
                        f"Action: {request.action}\n\n"
                        f"Access: may {request.access_kind}."
                    ),
                },
            ),
        ]
        if status == "pending":
            components.extend(
                [
                    A2UIComponent(
                        id="mcp-permission-allow",
                        component="Button",
                        properties={
                            "label": "Allow",
                            "variant": "primary",
                            "action": {
                                "event": {
                                    "name": "mcp_permission_decision",
                                    "context": {
                                        "requestId": pending.request_id,
                                        "decision": "allow",
                                    },
                                }
                            },
                        },
                    ),
                    A2UIComponent(
                        id="mcp-permission-allow-session",
                        component="Button",
                        properties={
                            "label": "Always allow",
                            "variant": "secondary",
                            "action": {
                                "event": {
                                    "name": "mcp_permission_decision",
                                    "context": {
                                        "requestId": pending.request_id,
                                        "decision": "allow_session",
                                    },
                                }
                            },
                        },
                    ),
                    A2UIComponent(
                        id="mcp-permission-deny",
                        component="Button",
                        properties={
                            "label": "Deny",
                            "variant": "secondary",
                            "action": {
                                "event": {
                                    "name": "mcp_permission_decision",
                                    "context": {
                                        "requestId": pending.request_id,
                                        "decision": "deny",
                                    },
                                }
                            },
                        },
                    ),
                    A2UIComponent(
                        id="mcp-permission-actions",
                        component="Row",
                        properties={
                            "children": [
                                "mcp-permission-allow",
                                "mcp-permission-allow-session",
                                "mcp-permission-deny",
                            ],
                            "gap": "8px",
                        },
                    ),
                ]
            )
            children.append("mcp-permission-actions")

        components.append(
            A2UIComponent(
                id="root",
                component="Card",
                properties={"children": children, "padding": "16px"},
            )
        )
        return components
