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


if __name__ == "__main__":
    unittest.main()
