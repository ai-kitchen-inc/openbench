"""Tests for the structured MCP error hierarchy."""

from __future__ import annotations

import json
import unittest

from openbench.mcp.errors import (
    MCPCapabilityError,
    MCPError,
    MCPPolicyDeniedError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
    MCPTransportError,
)


class TestMCPError(unittest.TestCase):
    def test_defaults(self):
        error = MCPError("boom")
        self.assertEqual(str(error), "boom")
        self.assertEqual(error.message, "boom")
        self.assertIsNone(error.server)
        self.assertIsNone(error.tool)
        self.assertIsNone(error.request_id)
        self.assertIsNone(error.correlation_id)
        self.assertEqual(error.retry_count, 0)
        self.assertEqual(error.data, {})
        self.assertIsNone(error.__cause__)

    def test_to_dict_payload(self):
        error = MCPError(
            "tool failed",
            server="files",
            tool="read",
            request_id="req-1",
            correlation_id="corr-1",
            retry_count=2,
            data={"detail": "denied"},
        )
        payload = error.to_dict()
        self.assertEqual(
            payload,
            {
                "type": "MCPError",
                "message": "tool failed",
                "server": "files",
                "tool": "read",
                "request_id": "req-1",
                "correlation_id": "corr-1",
                "retry_count": 2,
                "data": {"detail": "denied"},
            },
        )
        # The payload must survive JSON encoding — it crosses the wire.
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_to_dict_reports_subclass_type(self):
        payload = MCPToolExecutionError("x", server="s").to_dict()
        self.assertEqual(payload["type"], "MCPToolExecutionError")

    def test_cause_is_chained(self):
        cause = ValueError("root")
        error = MCPTransportError("wrapped", cause=cause)
        self.assertIs(error.__cause__, cause)

    def test_subclasses_are_mcp_errors(self):
        for cls in (
            MCPTransportError,
            MCPCapabilityError,
            MCPToolNotFoundError,
            MCPPolicyDeniedError,
            MCPToolExecutionError,
        ):
            with self.subTest(cls=cls.__name__):
                error = cls("x")
                self.assertIsInstance(error, MCPError)
                self.assertIsInstance(error, Exception)

    def test_data_none_becomes_empty_dict(self):
        self.assertEqual(MCPError("x", data=None).data, {})


if __name__ == "__main__":
    unittest.main()
