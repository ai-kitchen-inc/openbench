"""Tests for admin-managed runtime model settings."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.runtime_settings import (  # noqa: E402
    SETTINGS_KEY,
    RuntimeSettingsCache,
    default_runtime_settings,
    invalid_runtime_values,
    resolve_runtime_settings,
    runtime_settings_options,
)

pytestmark = pytest.mark.integration


class _MemoryStore:
    def __init__(self):
        self.data: dict = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, *, updated_by=""):
        self.data[key] = value


class TestRuntimeSettingsResolution(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        environ.pop("GENERAL_CHAT_MODEL", None)
        environ.pop("GENERAL_CHAT_VLM_MODEL", None)
        environ.pop("OPENBENCH_VLM_MODEL", None)

    def test_defaults(self):
        defaults = default_runtime_settings()
        self.assertEqual(defaults["llm_model"], "gemini-3.5-flash")
        self.assertEqual(defaults["vlm_model"], "gemini-2.5-flash")
        self.assertEqual(defaults["vector_store"], "postgres")

    def test_env_model_becomes_default_and_option(self):
        with patch.dict(environ, {"GENERAL_CHAT_MODEL": "gemini-custom"}, clear=False):
            self.assertEqual(default_runtime_settings()["llm_model"], "gemini-custom")
            self.assertIn("gemini-custom", runtime_settings_options()["llm_model"])

    def test_options_cover_every_field(self):
        options = runtime_settings_options()
        defaults = default_runtime_settings()
        for key, value in defaults.items():
            self.assertIn(value, options[key])
        self.assertEqual(options["vector_store"], ["postgres", "pinecone"])

    def test_resolve_merges_partial_and_drops_unknown(self):
        stored = {"llm_model": "gemini-2.5-pro", "made_up": "x"}
        resolved = resolve_runtime_settings(stored)
        self.assertEqual(resolved["llm_model"], "gemini-2.5-pro")
        self.assertNotIn("made_up", resolved)
        self.assertEqual(resolved["vector_store"], "postgres")

    def test_resolve_drops_values_outside_options(self):
        resolved = resolve_runtime_settings({"llm_model": "gemini-1.5-flash"})
        self.assertEqual(resolved["llm_model"], "gemini-3.5-flash")

    def test_resolve_garbage_returns_defaults(self):
        self.assertEqual(resolve_runtime_settings("junk"), default_runtime_settings())
        self.assertEqual(resolve_runtime_settings(None), default_runtime_settings())

    def test_invalid_values_reported_per_key(self):
        invalid = invalid_runtime_values(
            {"llm_model": "made-up-model", "vector_store": "postgres", "ignored": "x"}
        )
        self.assertEqual(list(invalid), ["llm_model"])
        self.assertEqual(invalid_runtime_values("junk"), {})

    def test_cache_update_persists_and_swaps(self):
        store = _MemoryStore()
        cache = RuntimeSettingsCache(store)
        merged = cache.update({"llm_model": "gemini-2.5-flash"}, updated_by="t@example.com")
        self.assertEqual(merged["llm_model"], "gemini-2.5-flash")
        self.assertEqual(cache.value["llm_model"], "gemini-2.5-flash")
        self.assertEqual(store.data[SETTINGS_KEY]["llm_model"], "gemini-2.5-flash")
        # A fresh cache over the same store sees the persisted value.
        self.assertEqual(
            RuntimeSettingsCache(store).value["llm_model"], "gemini-2.5-flash"
        )


class TestRuntimeSettingsEndpoints(unittest.TestCase):
    """Local-dev client (auth disabled → requester is admin by default)."""

    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        environ.pop("GENERAL_CHAT_MODEL", None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        self.create_agent = stack.enter_context(
            patch("general_chat.server.app.create_agent", return_value=agent)
        )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_get_returns_values_and_options(self):
        client = self._client()
        payload = client.get("/admin/runtime-settings").json()
        self.assertEqual(payload["values"]["llm_model"], "gemini-3.5-flash")
        self.assertEqual(payload["values"]["vector_store"], "postgres")
        self.assertIn("gemini-2.5-pro", payload["options"]["llm_model"])
        self.assertEqual(payload["options"]["vector_store"], ["postgres", "pinecone"])

    def test_put_persists_partial_update(self):
        client = self._client()
        response = client.put(
            "/admin/runtime-settings", json={"llm_model": "gemini-2.5-pro"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["values"]["llm_model"], "gemini-2.5-pro")
        # Untouched fields keep their defaults; the change survives a re-read.
        again = client.get("/admin/runtime-settings").json()
        self.assertEqual(again["values"]["llm_model"], "gemini-2.5-pro")
        self.assertEqual(again["values"]["vector_store"], "postgres")

    def test_put_rejects_unknown_model(self):
        client = self._client()
        response = client.put(
            "/admin/runtime-settings", json={"llm_model": "gemini-1.5-flash"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("llm_model", response.json()["detail"])

    def test_put_ignores_unknown_keys(self):
        client = self._client()
        response = client.put("/admin/runtime-settings", json={"made_up": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("made_up", response.json()["values"])

    def test_saved_model_reaches_agent_factory(self):
        client = self._client()
        response = client.put(
            "/admin/runtime-settings", json={"llm_model": "gemini-2.5-pro"}
        )
        self.assertEqual(response.status_code, 200)
        # The model change triggers a rebuild, and the factory passes the
        # stored model to create_agent.
        self.assertEqual(self.create_agent.call_args.kwargs["model"], "gemini-2.5-pro")

    def test_unchanged_model_does_not_rebuild(self):
        client = self._client()
        calls_before = self.create_agent.call_count
        # vector_store is stored-only: saving it must not rebuild the agent.
        response = client.put(
            "/admin/runtime-settings", json={"vector_store": "pinecone"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.create_agent.call_count, calls_before)

    def test_user_role_is_blocked(self):
        client = self._client()
        headers = {"X-Local-Role": "user"}
        self.assertEqual(
            client.get("/admin/runtime-settings", headers=headers).status_code, 403
        )
        self.assertEqual(
            client.put(
                "/admin/runtime-settings",
                headers=headers,
                json={"llm_model": "gemini-2.5-pro"},
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
