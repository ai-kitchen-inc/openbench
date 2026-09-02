"""Tests for the admin model catalog (unit + /admin/models routes)."""

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

from general_chat.model_catalog import (  # noqa: E402
    ModelCatalogCache,
    default_model_catalog,
    invalid_catalog_values,
    resolve_model_catalog,
)

pytestmark = pytest.mark.integration


class _MemoryStore:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, updated_by=""):
        self._data[key] = value


class TestModelCatalogResolution(unittest.TestCase):
    def test_defaults_seed_from_runtime_options(self):
        catalog = default_model_catalog()
        ids = [entry["id"] for entry in catalog["chatModels"]]
        self.assertIn("gemini-3.5-flash", ids)
        self.assertIn("gemini-2.5-pro", ids)
        self.assertEqual(len(catalog["embeddingModels"]), 1)
        self.assertEqual(catalog["embeddingModels"][0]["provider"], "google")

    def test_resolve_drops_malformed_and_duplicates(self):
        resolved = resolve_model_catalog(
            {
                "chatModels": [
                    {"id": "model-a", "label": "A"},
                    {"id": "model-a", "label": "dup"},
                    {"id": "  ", "label": "blank"},
                    "not-a-dict",
                ],
                "embeddingModels": [
                    {"id": "emb-1", "provider": "google", "dimension": 768},
                    {"id": "emb-2", "provider": "unknown", "dimension": 768},
                    {"id": "emb-3", "provider": "openai", "dimension": 4096},
                ],
            }
        )
        self.assertEqual(resolved["chatModels"], [{"id": "model-a", "label": "A"}])
        self.assertEqual(
            [entry["id"] for entry in resolved["embeddingModels"]], ["emb-1"]
        )

    def test_resolve_empty_chat_list_falls_back_to_seed(self):
        resolved = resolve_model_catalog({"chatModels": []})
        self.assertGreater(len(resolved["chatModels"]), 0)

    def test_invalid_values_flags_bad_entries(self):
        invalid = invalid_catalog_values(
            {
                "chatModels": [{"id": ""}],
                "embeddingModels": [{"id": "x", "provider": "google", "dimension": 0}],
            }
        )
        self.assertIn("chatModels[0]", invalid)
        self.assertIn("embeddingModels[0]", invalid)
        self.assertEqual(invalid_catalog_values({"chatModels": [{"id": "ok"}]}), {})

    def test_cache_update_replaces_lists(self):
        cache = ModelCatalogCache(_MemoryStore())
        cache.update({"chatModels": [{"id": "custom-model", "label": "Custom"}]})
        self.assertEqual(cache.chat_model_ids(), ["custom-model"])
        # Embedding list untouched by a chat-only update.
        self.assertEqual(len(cache.value["embeddingModels"]), 1)
        self.assertIsNotNone(cache.embedding_model("gemini-embedding-001"))
        self.assertIsNone(cache.embedding_model("missing"))


class TestModelCatalogRoutes(unittest.TestCase):
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
                    "GENERAL_CHAT_MEMORY_DB": str(tmpdir / "memory.db"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        environ.pop("GENERAL_CHAT_LOCAL_GROUP", None)
        stack.enter_context(
            patch("general_chat.server.app.create_agent", side_effect=lambda **kw: Mock())
        )
        # create_app wires the module-global options provider to this
        # app's catalog cache — reset it so later tests see the default.
        from general_chat.runtime_settings import set_model_options_provider

        self.addCleanup(set_model_options_provider, None)
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_get_returns_seeded_catalog(self):
        client = self._client()
        payload = client.get("/admin/models").json()
        self.assertIn("gemini-3.5-flash", [m["id"] for m in payload["chatModels"]])
        self.assertEqual(payload["embeddingModels"][0]["id"], "gemini-embedding-001")

    def test_put_adds_model_and_feeds_runtime_options(self):
        client = self._client()
        catalog = client.get("/admin/models").json()
        catalog["chatModels"].append({"id": "gemini-4-pro-preview", "label": "Gemini 4 Pro"})
        updated = client.put("/admin/models", json=catalog)
        self.assertEqual(updated.status_code, 200)
        self.assertIn(
            "gemini-4-pro-preview", [m["id"] for m in updated.json()["chatModels"]]
        )
        options = client.get("/admin/runtime-settings").json()["options"]
        self.assertIn("gemini-4-pro-preview", options["llm_model"])
        # And the per-agent model validation accepts it.
        client.post("/admin/agents", json={"name": "Uji", "description": "Uji model."})
        response = client.put("/admin/agents/uji", json={"model": "gemini-4-pro-preview"})
        self.assertEqual(response.status_code, 200)

    def test_put_rejects_removing_active_default(self):
        client = self._client()
        active = client.get("/admin/runtime-settings").json()["values"]["llm_model"]
        catalog = client.get("/admin/models").json()
        catalog["chatModels"] = [
            entry for entry in catalog["chatModels"] if entry["id"] != active
        ]
        response = client.put("/admin/models", json=catalog)
        self.assertEqual(response.status_code, 400)
        self.assertIn(active, response.json()["detail"])

    def test_put_rejects_malformed_entries(self):
        client = self._client()
        response = client.put("/admin/models", json={"chatModels": [{"id": ""}]})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
