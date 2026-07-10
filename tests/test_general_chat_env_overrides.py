"""Env-gated override hooks in General Chat (soul dir, agent goal, owner override)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))


pytestmark = pytest.mark.integration


class TestPersonaDirOverride(unittest.TestCase):
    def test_default_is_example_soul_dir(self):
        from general_chat.agent import get_persona_dir

        with patch.dict(environ, {}, clear=False):
            environ.pop("GENERAL_CHAT_SOUL_DIR", None)
            self.assertEqual(get_persona_dir(), (GENERAL_CHAT_SRC.parent / "soul").resolve())

    def test_env_override_wins(self):
        from general_chat.agent import get_persona_dir

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(environ, {"GENERAL_CHAT_SOUL_DIR": tmp}, clear=False):
                self.assertEqual(get_persona_dir(), Path(tmp).resolve())

    def test_blank_override_falls_back_to_default(self):
        from general_chat.agent import get_persona_dir

        with patch.dict(environ, {"GENERAL_CHAT_SOUL_DIR": "  "}, clear=False):
            self.assertEqual(get_persona_dir(), (GENERAL_CHAT_SRC.parent / "soul").resolve())


class TestCurrentOwnerOverride(unittest.TestCase):
    def _request(self, **state) -> SimpleNamespace:
        return SimpleNamespace(state=SimpleNamespace(**state))

    def test_owner_override_wins_over_everything(self):
        from general_chat.server.auth import current_owner

        request = self._request(owner_override="Admin ")
        self.assertEqual(current_owner(request), "admin")

    def test_without_override_local_sentinel_when_auth_disabled(self):
        from general_chat.server.auth import current_owner

        with patch.dict(environ, {"OPENBENCH_AUTH_DISABLED": "1"}, clear=False):
            self.assertEqual(current_owner(self._request()), "local")

    def test_empty_override_is_ignored(self):
        from general_chat.server.auth import current_owner

        with patch.dict(environ, {"OPENBENCH_AUTH_DISABLED": "1"}, clear=False):
            request = self._request(owner_override="")
            self.assertEqual(current_owner(request), "local")


class TestAgentGoalOverride(unittest.TestCase):
    def _create_agent_with_env(self, extra_env: dict[str, str]) -> Mock:
        """Run create_agent with collaborators mocked; return the BaseAgent mock class."""
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    # Nonexistent soul dir -> persona None (skips file reads).
                    "GENERAL_CHAT_SOUL_DIR": str(Path(tempfile.gettempdir()) / "no-such-soul"),
                    "GENERAL_CHAT_MCP_ENABLED": "0",
                    "GENERAL_CHAT_DASHBOARD_SKILL_ENABLED": "0",
                    **extra_env,
                },
                clear=False,
            )
        )
        import general_chat.agent as agent_module

        stack.enter_context(patch.object(agent_module, "_configure_general_chat_provider"))
        stack.enter_context(
            patch.object(agent_module, "_create_vision_agent", return_value=(None, {}))
        )
        stack.enter_context(patch.object(agent_module, "_attach_dashboard_revision_context"))
        base_agent_cls = stack.enter_context(patch.object(agent_module, "BaseAgent"))
        agent_module.create_agent(api_key="test-key")
        return base_agent_cls

    def test_default_goal_when_env_unset(self):
        environ.pop("GENERAL_CHAT_AGENT_GOAL", None)
        base_agent_cls = self._create_agent_with_env({})
        goal = base_agent_cls.call_args.kwargs["goal"]
        self.assertTrue(goal.startswith("Help users by answering questions"))

    def test_env_goal_overrides_default(self):
        base_agent_cls = self._create_agent_with_env(
            {"GENERAL_CHAT_AGENT_GOAL": "Answer only from curated sources."}
        )
        goal = base_agent_cls.call_args.kwargs["goal"]
        self.assertEqual(goal, "Answer only from curated sources.")


class TestSourceContextLabelOverride(unittest.TestCase):
    def _record(self):
        from general_chat.sources import SourceRecord

        return SourceRecord.create(
            session_id="thread-1",
            name="kb-doc",
            kind="text",
            mime_type="text/plain",
            size_bytes=5,
            url="",
            text="hello",
            status="ready",
        )

    def test_default_label_is_unchanged(self):
        from general_chat.server.handler import _source_record_attachments

        environ.pop("GENERAL_CHAT_SOURCE_CONTEXT_LABEL", None)
        attachments = _source_record_attachments([self._record()])
        self.assertIn(
            "Optional context extracted from this user-added source.",
            attachments[0].extracted_text,
        )

    def test_env_label_overrides_default(self):
        from general_chat.server.handler import _source_record_attachments

        with patch.dict(
            environ,
            {"GENERAL_CHAT_SOURCE_CONTEXT_LABEL": "Authoritative knowledge-base source."},
            clear=False,
        ):
            attachments = _source_record_attachments([self._record()])
        text = attachments[0].extracted_text
        self.assertIn("Authoritative knowledge-base source.", text)
        self.assertNotIn("Optional context", text)

    def test_stale_context_redaction_still_fires_with_custom_label(self):
        from general_chat.server.handler import _redact_stale_source_context
        from openbench.intelligence.base import Message, MessageRole

        content = (
            "Goal: hi\n\nContext data: "
            '{"attachments": [{"name": "kb-doc", "content": "Authoritative source."}]}'
        )
        redacted, changed = _redact_stale_source_context(
            [Message(role=MessageRole.USER, content=content)]
        )
        self.assertTrue(changed)
        self.assertNotIn("kb-doc", redacted[0].content)


class TestSharedSourcesMode(unittest.TestCase):
    """GENERAL_CHAT_SHARED_SOURCES_* pins /awp grounding to one curated thread."""

    def _client(self, extra_env: dict[str, str]) -> "TestClient":
        from fastapi.testclient import TestClient

        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(self.tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(self.tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(self.tmpdir / "downloads"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                    **extra_env,
                },
                clear=False,
            )
        )
        for name in ("GENERAL_CHAT_SHARED_SOURCES_OWNER", "GENERAL_CHAT_SHARED_SOURCES_THREAD"):
            if name not in extra_env:
                environ.pop(name, None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))

        from fastapi.responses import JSONResponse

        self.handler_cls = Mock()
        handler_instance = Mock()

        async def _handle(_request):
            return JSONResponse({"ok": True})

        handler_instance.handle = _handle
        self.handler_cls.return_value = handler_instance
        stack.enter_context(
            patch("general_chat.server.app.GeneralChatHandler", self.handler_cls)
        )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_shared_mode_uses_curated_thread_and_skips_cleanup(self):
        client = self._client(
            {
                "GENERAL_CHAT_SHARED_SOURCES_OWNER": "local",
                "GENERAL_CHAT_SHARED_SOURCES_THREAD": "controlled-sources",
            }
        )
        client.post(
            "/chat/sources/controlled-sources/text",
            json={"name": "kb-note", "text": "The Zylor Bridge opened in 1987."},
        )

        response = client.post("/awp", json={"threadId": "guest-session-1"})

        self.assertEqual(response.status_code, 200)
        kwargs = self.handler_cls.call_args.kwargs
        self.assertEqual([r.name for r in kwargs["source_records"]], ["kb-note"])
        self.assertIsNone(kwargs["on_stream_complete"])

    def test_default_mode_uses_request_session_and_cleanup(self):
        client = self._client({})
        client.post(
            "/chat/sources/my-session/text",
            json={"name": "own-note", "text": "session-scoped context"},
        )

        response = client.post("/awp", json={"threadId": "my-session"})

        self.assertEqual(response.status_code, 200)
        kwargs = self.handler_cls.call_args.kwargs
        self.assertEqual([r.name for r in kwargs["source_records"]], ["own-note"])
        self.assertIsNotNone(kwargs["on_stream_complete"])


if __name__ == "__main__":
    unittest.main()
