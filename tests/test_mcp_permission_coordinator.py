"""Tests for the General Chat MCP permission coordinator's run-scoped 'Always allow'.

"Always allow" approves every tool call in the current run (one user message),
and resets on the next message (a new run_id).
"""

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
        action=f"run {tool_name}",
    )


class TestRunScopedAllowAll(unittest.TestCase):
    def _seed_pending(self, coord, *, request_id, session_id, run_id, request, with_io=False):
        pending = PendingMCPPermission(
            request_id=request_id,
            session_id=session_id,
            run_id=run_id,
            surface_id=f"s-{request_id}",
            request=request,
            event=threading.Event(),
            queue=MagicMock() if with_io else None,
            loop=MagicMock() if with_io else None,
        )
        with coord._lock:
            coord._pending[request_id] = pending
        return pending

    def test_allow_session_records_run(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        pending = self._seed_pending(
            coord, request_id="r1", session_id="sA", run_id="run-1", request=_request()
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
        self.assertIn("run-1", coord._allow_all_runs)

    def test_same_run_different_tool_skips_prompt(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        coord._allow_all_runs["run-1"] = True
        loop = MagicMock()

        # A DIFFERENT tool in the same run is auto-approved without a prompt.
        result = coord.request_permission(
            session_id="sA",
            run_id="run-1",
            request=_request("export_excel"),
            queue=MagicMock(),
            loop=loop,
        )

        self.assertEqual(result, "yes")
        loop.call_soon_threadsafe.assert_not_called()

    def test_next_run_prompts_again(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.05)
        coord._allow_all_runs["run-1"] = True
        loop = MagicMock()

        # A new message = new run_id, so it must prompt again (here, time out).
        result = coord.request_permission(
            session_id="sA",
            run_id="run-2",
            request=_request(),
            queue=MagicMock(),
            loop=loop,
        )

        self.assertIsNone(result)
        loop.call_soon_threadsafe.assert_called()  # a surface WAS emitted

    def test_allow_session_releases_sibling_pendings(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        clicked = self._seed_pending(
            coord, request_id="r1", session_id="sA", run_id="run-1", request=_request("a")
        )
        sibling = self._seed_pending(
            coord,
            request_id="r2",
            session_id="sA",
            run_id="run-1",
            request=_request("b"),
            with_io=True,
        )
        other_run = self._seed_pending(
            coord, request_id="r3", session_id="sA", run_id="run-9", request=_request("c"),
            with_io=True,
        )

        coord.resolve_action(
            ActionData(
                name="mcp_permission_decision",
                surface_id="s-r1",
                context={"requestId": "r1", "decision": "allow_session"},
                thread_id="sA",
            )
        )

        # Clicked + same-run sibling both released with "yes".
        self.assertEqual(clicked.response, "yes")
        self.assertTrue(sibling.event.is_set())
        self.assertEqual(sibling.response, "yes")
        # A pending from a different run is untouched.
        self.assertFalse(other_run.event.is_set())
        self.assertIsNone(other_run.response)

    def test_plain_allow_does_not_record_run(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        self._seed_pending(
            coord, request_id="r2", session_id="sA", run_id="run-1", request=_request()
        )

        coord.resolve_action(
            ActionData(
                name="mcp_permission_decision",
                surface_id="s-r2",
                context={"requestId": "r2", "decision": "allow"},
                thread_id="sA",
            )
        )

        self.assertNotIn("run-1", coord._allow_all_runs)

    def test_allow_all_runs_is_bounded(self):
        coord = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.1)
        from general_chat.server.mcp_permissions import _ALLOW_ALL_RUNS_CAP

        for i in range(_ALLOW_ALL_RUNS_CAP + 50):
            pending = self._seed_pending(
                coord,
                request_id=f"r{i}",
                session_id="sA",
                run_id=f"run-{i}",
                request=_request(),
            )
            coord.resolve_action(
                ActionData(
                    name="mcp_permission_decision",
                    surface_id=pending.surface_id,
                    context={"requestId": pending.request_id, "decision": "allow_session"},
                    thread_id="sA",
                )
            )

        self.assertLessEqual(len(coord._allow_all_runs), _ALLOW_ALL_RUNS_CAP)
        # Oldest evicted, newest retained.
        self.assertNotIn("run-0", coord._allow_all_runs)
        self.assertIn(f"run-{_ALLOW_ALL_RUNS_CAP + 49}", coord._allow_all_runs)


if __name__ == "__main__":
    unittest.main()
