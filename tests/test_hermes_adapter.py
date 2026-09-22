"""Tests for HermesAdapter and HermesAgent (HTTP fully mocked)."""

import json
import unittest
from unittest.mock import MagicMock

import requests

from openbench.adapters.hermes import (
    SESSION_HEADER,
    HermesAdapter,
    HermesAgent,
    HermesError,
)
from openbench.core.abstractions import Agent, ExecutionContext, FrameworkAdapter


def _json_response(body, status=200, headers=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = json.dumps(body)
    response.headers = headers or {}
    return response


def _sse_response(lines, status=200):
    response = MagicMock()
    response.status_code = status
    response.iter_lines.return_value = iter(lines)
    response.headers = {}
    return response


def _chunk(text):
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})


def _adapter(http, **kwargs):
    return HermesAdapter("http://127.0.0.1:8643/", api_key="key-a", session=http, **kwargs)


class TestHermesAdapterInit(unittest.TestCase):
    def test_is_framework_adapter(self):
        adapter = _adapter(MagicMock())
        self.assertIsInstance(adapter, FrameworkAdapter)
        self.assertEqual(adapter.framework_name, "hermes")

    def test_base_url_normalized(self):
        self.assertEqual(_adapter(MagicMock()).base_url, "http://127.0.0.1:8643")

    def test_requires_base_url_and_key(self):
        with self.assertRaises(ValueError):
            HermesAdapter(" ", api_key="k")
        with self.assertRaises(ValueError):
            HermesAdapter("http://x", api_key=" ")

    def test_repr_hides_api_key(self):
        self.assertNotIn("key-a", repr(_adapter(MagicMock())))


class TestHermesAdapterInvoke(unittest.TestCase):
    def test_invoke_posts_bearer_and_returns_output(self):
        http = MagicMock()
        http.post.return_value = _json_response(
            {
                "choices": [{"message": {"content": "halo"}}],
                "usage": {"total_tokens": 12},
            },
            headers={SESSION_HEADER: "s1"},
        )
        result = _adapter(http).invoke("hi", {"session_id": "s1"})

        self.assertEqual(result["output"], "halo")
        self.assertEqual(result["metadata"]["usage"], {"total_tokens": 12})
        self.assertEqual(result["metadata"]["hermes_session_id"], "s1")
        _, kwargs = http.post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer key-a")
        self.assertEqual(kwargs["headers"][SESSION_HEADER], "s1")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "hi"}])
        self.assertFalse(kwargs["json"]["stream"])
        self.assertEqual(http.post.call_args[0][0], "http://127.0.0.1:8643/v1/chat/completions")

    def test_invoke_includes_filtered_history(self):
        http = MagicMock()
        http.post.return_value = _json_response({"choices": [{"message": {"content": "ok"}}]})
        history = [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "  "},
            "junk",
        ]
        _adapter(http).invoke({"goal": "q2"}, {"messages": history})

        sent = http.post.call_args[1]["json"]["messages"]
        self.assertEqual(
            sent,
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ],
        )

    def test_invoke_no_session_header_without_session_id(self):
        http = MagicMock()
        http.post.return_value = _json_response({"choices": [{"message": {"content": "ok"}}]})
        _adapter(http).invoke("hi")
        self.assertNotIn(SESSION_HEADER, http.post.call_args[1]["headers"])

    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):
            _adapter(MagicMock()).invoke("   ")

    def test_http_error_raises_with_status(self):
        http = MagicMock()
        http.post.return_value = _json_response({"error": {"message": "Invalid API key"}}, 401)
        with self.assertRaises(HermesError) as ctx:
            _adapter(http).invoke("hi")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Invalid API key", str(ctx.exception))

    def test_connection_failure_raises_hermes_error(self):
        http = MagicMock()
        http.post.side_effect = requests.ConnectionError("refused")
        with self.assertRaises(HermesError):
            _adapter(http).invoke("hi")

    def test_non_json_response_raises(self):
        http = MagicMock()
        response = _json_response({})
        response.json.side_effect = ValueError("no json")
        http.post.return_value = response
        with self.assertRaises(HermesError):
            _adapter(http).invoke("hi")


class TestHermesAdapterStream(unittest.TestCase):
    def test_stream_yields_deltas_and_stops_at_done(self):
        http = MagicMock()
        http.post.return_value = _sse_response(
            [_chunk("Ha"), "", _chunk("lo"), "", "data: [DONE]", _chunk("never")]
        )
        self.assertEqual(list(_adapter(http).stream("hi")), ["Ha", "lo"])
        self.assertTrue(http.post.call_args[1]["stream"])
        self.assertTrue(http.post.call_args[1]["json"]["stream"])

    def test_stream_routes_tool_progress_and_usage(self):
        http = MagicMock()
        http.post.return_value = _sse_response(
            [
                "event: hermes.tool.progress",
                "data: "
                + json.dumps({"tool": "mcp_db_query", "label": "Query DB", "status": "running"}),
                "",
                "event: hermes.tool.progress",
                "data: " + json.dumps({"tool": "mcp_db_query", "status": "completed"}),
                "",
                _chunk("done"),
                "data: " + json.dumps({"choices": [], "usage": {"total_tokens": 7}}),
                "data: not-json",
                "data: [DONE]",
            ]
        )
        labels, usage = [], {}
        out = list(_adapter(http).stream("hi", on_progress=labels.append, usage_sink=usage))

        self.assertEqual(out, ["done"])
        self.assertEqual(labels, ["Query DB"])
        self.assertEqual(usage, {"total_tokens": 7})

    def test_stream_closes_response(self):
        http = MagicMock()
        response = _sse_response(["data: [DONE]"])
        http.post.return_value = response
        list(_adapter(http).stream("hi"))
        response.close.assert_called_once()


class TestHermesAdapterHealth(unittest.TestCase):
    def test_health_true_on_200(self):
        http = MagicMock()
        http.get.return_value = _json_response({"status": "ok"})
        self.assertTrue(_adapter(http).health())

    def test_health_false_on_connection_error(self):
        http = MagicMock()
        http.get.side_effect = requests.ConnectionError("down")
        self.assertFalse(_adapter(http).health())


class TestHermesAgent(unittest.TestCase):
    def _context(self, goal="q2"):
        return ExecutionContext(
            goal=goal,
            data={
                "session": {
                    "sessionId": "sess-1",
                    "messages": [
                        {"role": "user", "content": "q1"},
                        {"role": "assistant", "content": "a1"},
                        {"role": "user", "content": goal},
                    ],
                }
            },
        )

    def test_is_agent_with_model(self):
        agent = HermesAgent(_adapter(MagicMock(), model="finance"))
        self.assertIsInstance(agent, Agent)
        self.assertEqual(agent.agent_type, "hermes")
        self.assertEqual(agent.model, "finance")
        self.assertEqual(agent.estimate_cost(self._context()), 0.0)

    def test_execute_streams_chunks_progress_and_session_scope(self):
        http = MagicMock()
        http.post.return_value = _sse_response(
            [
                "event: hermes.tool.progress",
                "data: " + json.dumps({"tool": "search"}),
                "",
                _chunk("Ja"),
                _chunk("wab"),
                "data: " + json.dumps({"choices": [], "usage": {"total_tokens": 42}}),
                "data: [DONE]",
            ]
        )
        chunks, phases = [], []
        result = HermesAgent(_adapter(http)).execute(
            self._context(),
            on_chunk=chunks.append,
            on_progress=lambda event: phases.append(event.phase),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Jawab")
        self.assertEqual(chunks, ["Ja", "wab"])
        self.assertEqual(phases, ["search"])
        self.assertEqual(result.tokens_used, 42)
        kwargs = http.post.call_args[1]
        self.assertEqual(kwargs["headers"][SESSION_HEADER], "sess-1")
        # Current user turn is not duplicated in the history.
        self.assertEqual(
            kwargs["json"]["messages"],
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ],
        )

    def test_execute_without_session_data(self):
        http = MagicMock()
        http.post.return_value = _sse_response([_chunk("ok"), "data: [DONE]"])
        result = HermesAgent(_adapter(http)).execute(ExecutionContext(goal="hi"))
        self.assertEqual(result.output, "ok")
        self.assertIsNone(result.tokens_used)

    def test_execute_returns_error_result_on_hermes_failure(self):
        http = MagicMock()
        http.post.return_value = _json_response({"error": "boom"}, 500)
        result = HermesAgent(_adapter(http)).execute(self._context())
        self.assertEqual(result.status, "error")
        self.assertIn("500", result.metadata["error"])


if __name__ == "__main__":
    unittest.main()
