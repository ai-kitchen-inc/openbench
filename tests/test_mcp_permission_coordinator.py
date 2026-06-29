"""Tests for the General Chat MCP permission coordinator's 'Always allow'."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from openbench.chat.transport.agui_actions import ActionData
from openbench.mcp.permissions import MCPPermissionRequest
from openbench.mcp.policy import RiskLevel

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.mcp_permissions import (  # noqa: E402
    GeneralChatMCPPermissionCoordinator,
    PendingMCPPermission,
)


def _request(tool_name: str = "aggregate_data") -> MCPPermissionRequest:
    return MCPPermissionRequest(
        tool_name=tool_name,
        purpose="run an aggregation",
        arguments={"query": "SELECT 1"},
        risk=RiskLevel.READ,
        action="run aggregate_data",
    )


class TestAlwaysAllow(unittest.TestCase):
    def _seed_pending(self, coord, *, request_id, session_id, request):
        pending = PendingMCPPermission(
            request_id=request_id,
            session_id=session_id,
            surface_id=f"s-{request_id}",
            request=request,
            event=threading.Event(),
        )
        with coord._lock:
            coord._pending[request_id] = pending
        return pending

    def test_allow_session_approves_and_records_tool(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        pending = self._seed_pending(
            coord, request_id="r1", session_id="sA", request=_request()
        )

        coord.resolve_action(
            ActionData(
                name="mcp_permission_decision",
                surface_id="s-r1",
                context={"requestId": "r1", "decision": "allow_session"},
                thread_id="sA",
            )
        )

        self.assertEqual(pending.response, "yes")
        self.assertTrue(pending.event.is_set())
        self.assertIn("aggregate_data", coord._always_allowed.get("sA", set()))

    def test_always_allowed_tool_skips_prompt(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        coord._always_allowed["sA"] = {"aggregate_data"}
        loop = MagicMock()

        result = coord.request_permission(
            session_id="sA", request=_request(), queue=MagicMock(), loop=loop
        )

        self.assertEqual(result, "yes")
        # No surface was emitted — the prompt was skipped entirely.
        loop.call_soon_threadsafe.assert_not_called()

    def test_other_session_is_not_auto_approved(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.05)
        coord._always_allowed["sA"] = {"aggregate_data"}
        loop = MagicMock()

        # Session B never approved the tool, so it must still prompt (and here
        # time out, since no decision arrives).
        result = coord.request_permission(
            session_id="sB", request=_request(), queue=MagicMock(), loop=loop
        )

        self.assertIsNone(result)
        loop.call_soon_threadsafe.assert_called()  # a surface WAS emitted

    def test_plain_allow_does_not_record_always(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        self._seed_pending(coord, request_id="r2", session_id="sA", request=_request())

        coord.resolve_action(
            ActionData(
                name="mcp_permission_decision",
                surface_id="s-r2",
                context={"requestId": "r2", "decision": "allow"},
                thread_id="sA",
            )
        )

        self.assertNotIn("aggregate_data", coord._always_allowed.get("sA", set()))


if __name__ == "__main__":
    unittest.main()
