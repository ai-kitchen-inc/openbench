"""Tests for GET /admin/skills/health and the options skill warnings."""

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

pytestmark = pytest.mark.integration


class TestSkillHealth(unittest.TestCase):
    def _client(self, *, broken_custom_skill: bool = False) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        custom_dir = tmpdir / "skills"
        custom_dir.mkdir(parents=True)
        if broken_custom_skill:
            # SKILL.md without an H1 makes Skill.from_dir raise ValueError,
            # while the directory listing still counts it as a skill.
            bad = custom_dir / "rusak"
            bad.mkdir()
            (bad / "SKILL.md").write_text("no heading here\n", encoding="utf-8")
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
                    "GENERAL_CHAT_CUSTOM_SKILLS_DIR": str(custom_dir),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        environ.pop("GENERAL_CHAT_LOCAL_GROUP", None)
        environ.pop("GENERAL_CHAT_SOURCE_INDEX_ENABLED", None)
        stack.enter_context(
            patch("general_chat.server.app.create_agent", side_effect=lambda **kw: Mock())
        )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_health_loads_every_sdk_skill(self):
        client = self._client()
        payload = client.get("/admin/skills/health").json()
        by_id = {entry["id"]: entry for entry in payload["skills"]}

        web_search = by_id["web-search"]
        self.assertTrue(web_search["ok"])
        self.assertEqual(
            set(web_search["tools"]), {"web_search", "web_search_multi", "fetch_url"}
        )
        self.assertEqual(web_search["warnings"], [])
        self.assertEqual(web_search["source"], "sdk")

        # Every listed SDK skill actually loads.
        sdk_entries = [e for e in payload["skills"] if e["source"] == "sdk"]
        self.assertGreater(len(sdk_entries), 5)
        self.assertTrue(all(entry["ok"] for entry in sdk_entries))

    def test_health_flags_index_bound_skills_when_index_off(self):
        client = self._client()
        payload = client.get("/admin/skills/health").json()
        by_id = {entry["id"]: entry for entry in payload["skills"]}
        for skill_id in ("source-retrieval", "table-query"):
            if skill_id not in by_id:
                continue
            self.assertTrue(
                any("indeks sumber" in warning for warning in by_id[skill_id]["warnings"]),
                skill_id,
            )

    def test_health_isolates_a_broken_custom_skill(self):
        client = self._client(broken_custom_skill=True)
        response = client.get("/admin/skills/health")
        self.assertEqual(response.status_code, 200)
        by_id = {entry["id"]: entry for entry in response.json()["skills"]}
        broken = by_id["rusak"]
        self.assertFalse(broken["ok"])
        self.assertTrue(broken["error"])
        self.assertEqual(broken["source"], "custom")
        # Healthy skills are unaffected by the broken one.
        self.assertTrue(by_id["web-search"]["ok"])

    def test_options_surfaces_sdk_skill_warnings(self):
        client = self._client()
        options = client.get("/admin/agents/options").json()
        warnings = options["sdkSkillWarnings"]
        self.assertIsInstance(warnings, dict)
        self.assertNotIn("web-search", warnings)
        if "source-retrieval" in options["sdkSkills"]:
            self.assertIn("source-retrieval", warnings)


if __name__ == "__main__":
    unittest.main()
