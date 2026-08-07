"""Tests for General Chat custom skill store and admin routes."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.custom_skills import CustomSkillError, CustomSkillStore  # noqa: E402

ADMIN = FirebaseUser(uid="admin-1", email="boss@example.com")
ADMIN_H = {"Authorization": "Bearer token-admin"}


class TestCustomSkillStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env_patch = patch.dict(environ, {"GENERAL_CHAT_CUSTOM_SKILLS_DIR": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.store = CustomSkillStore(self._tmp.name)

    def test_save_list_delete_round_trip(self):
        saved = self.store.save(
            "risk-review",
            name="Risk Review",
            description="Reviews decision risks.",
            triggers=["risk", "mitigation"],
            instructions="Always return risks, impact, and mitigation.",
        )
        self.assertEqual(saved["id"], "risk-review")
        self.assertEqual(saved["name"], "Risk Review")
        self.assertIn("risk", saved["triggers"])
        self.assertIn("Always return", saved["skill_md"])
        paths = self.store.paths()
        self.assertEqual(len(paths), 1)
        self.assertTrue((paths[0] / "SKILL.md").is_file())

        listed = self.store.list()
        self.assertEqual([skill["id"] for skill in listed], ["risk-review"])
        self.assertTrue(self.store.delete("risk-review"))
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.store.delete("risk-review"))

    def test_save_rejects_invalid_payload(self):
        with self.assertRaises(CustomSkillError):
            self.store.save("1-bad", name="Bad", instructions="Do things.")
        with self.assertRaises(CustomSkillError):
            self.store.save("ok-skill", name="", instructions="Do things.")
        with self.assertRaises(CustomSkillError):
            self.store.save("ok-skill", name="OK", instructions="")
        with self.assertRaises(CustomSkillError):
            self.store.save("ok-skill", name="OK", instructions="Do things.", version="vNext")


class TestCustomSkillRoutes(unittest.TestCase):
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
                    "GENERAL_CHAT_FIREBASE_PROJECT_ID": "demo-project",
                    "GENERAL_CHAT_BOOTSTRAP_ADMIN": "boss@example.com",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                    "GENERAL_CHAT_CUSTOM_SKILLS_DIR": str(tmpdir / "skills"),
                },
                clear=False,
            )
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)

        self.create_agent_calls: list[dict] = []

        def _fake_create_agent(**kwargs):
            self.create_agent_calls.append(kwargs)
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = kwargs.get("persona")
            agent._skill_registry = None
            return agent

        stack.enter_context(
            patch("general_chat.server.app.create_agent", side_effect=_fake_create_agent)
        )

        verifier = Mock()
        verifier.verify.return_value = ADMIN
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    def test_routes_require_admin_auth(self):
        client = self._client()
        self.assertEqual(client.get("/admin/custom-skills").status_code, 401)

    def test_save_list_delete_flow_rebuilds_agent_with_skill_path(self):
        client = self._client()
        builds_before = len(self.create_agent_calls)
        response = client.post(
            "/admin/custom-skills",
            headers=ADMIN_H,
            json={
                "id": "risk-review",
                "name": "Risk Review",
                "description": "Reviews decision risks.",
                "triggers": ["risk", "mitigation"],
                "instructions": "Return a table with risk, impact, mitigation, and owner.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "risk-review")
        self.assertEqual(len(self.create_agent_calls), builds_before + 1)
        loaded_paths = self.create_agent_calls[-1]["custom_skill_paths"]
        self.assertEqual(len(loaded_paths), 1)
        self.assertTrue((Path(loaded_paths[0]) / "SKILL.md").is_file())

        listed = client.get("/admin/custom-skills", headers=ADMIN_H)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([skill["id"] for skill in listed.json()["skills"]], ["risk-review"])

        deleted = client.delete("/admin/custom-skills/risk-review", headers=ADMIN_H)
        self.assertEqual(deleted.status_code, 200)
        second_delete = client.delete("/admin/custom-skills/risk-review", headers=ADMIN_H)
        self.assertEqual(second_delete.status_code, 404)

    def test_save_validation_errors_are_400(self):
        client = self._client()
        response = client.post(
            "/admin/custom-skills",
            headers=ADMIN_H,
            json={"id": "bad-skill", "name": "Bad", "instructions": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("instructions are required", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
