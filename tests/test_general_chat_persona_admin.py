"""Tests for admin-managed persona templates and agent hot-rebuild."""

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

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.persona_templates import (  # noqa: E402
    DEFAULT_TEMPLATE_ID,
    TEMPLATES,
    get_template,
    normalize_persona_settings,
    persona_from_settings,
    settings_from_template,
)

pytestmark = pytest.mark.integration

ADMIN = FirebaseUser(uid="uid-admin", email="boss@example.com")
MEMBER = FirebaseUser(uid="uid-member", email="member@example.com")
ADMIN_H = {"Authorization": "Bearer token-admin"}
MEMBER_H = {"Authorization": "Bearer token-member"}


class TestPersonaTemplates(unittest.TestCase):
    def test_three_templates_exist_with_soft_default(self):
        ids = [template.id for template in TEMPLATES]
        self.assertIn("soft-grounded", ids)
        self.assertIn("strict", ids)
        self.assertIn("general", ids)
        self.assertEqual(DEFAULT_TEMPLATE_ID, "soft-grounded")

    def test_settings_from_template_roundtrips_to_persona(self):
        template = get_template("strict")
        value = settings_from_template(template)
        persona, goal, label = persona_from_settings(value)
        self.assertIsNotNone(persona)
        self.assertIn("ONLY source of knowledge", persona.soul)
        self.assertIn("strictly from the curated source context", goal)
        self.assertIn("ONLY from these sources", label)

    def test_soft_template_allows_general_knowledge(self):
        value = settings_from_template(get_template("soft-grounded"))
        persona, goal, label = persona_from_settings(value)
        self.assertIn("general knowledge", persona.soul)
        self.assertEqual(goal, "")
        self.assertIn("general knowledge remains allowed", label)

    def test_persona_from_missing_or_empty_settings_is_none(self):
        self.assertEqual(persona_from_settings(None), (None, "", ""))
        self.assertEqual(persona_from_settings({}), (None, "", ""))
        self.assertEqual(
            persona_from_settings({"soul": "  ", "style": "", "agents": ""}),
            (None, "", ""),
        )

    def test_normalize_accepts_camel_case_label(self):
        normalized = normalize_persona_settings(
            {"soul": "I am X.", "sourceContextLabel": "Label"}
        )
        self.assertEqual(normalized["source_context_label"], "Label")


class TestPersonaAdminEndpoints(unittest.TestCase):
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
                },
                clear=False,
            )
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)
        environ.pop("GENERAL_CHAT_SOUL_DIR", None)

        # create_agent mock records the persona/goal it was invoked with
        # and returns a fresh Mock each call so rebuilds are observable.
        self.create_agent_calls: list[dict] = []
        self.fail_next_create = False

        def _fake_create_agent(**kwargs):
            if self.fail_next_create:
                raise RuntimeError("boom")
            self.create_agent_calls.append(kwargs)
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = kwargs.get("persona")
            agent._skill_registry = None
            return agent

        stack.enter_context(
            patch("general_chat.server.app.create_agent", side_effect=_fake_create_agent)
        )

        tokens = {"token-admin": ADMIN, "token-member": MEMBER}
        verifier = Mock()
        verifier.verify.side_effect = lambda token, **_kw: tokens[token]
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app
        from general_chat.server.handler import set_source_context_label_override

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        # The DB persona sets a module-level source-label override; clear it
        # after each test so it can't leak into unrelated suites.
        self.addCleanup(set_source_context_label_override, None)
        # Member must exist to test 403s on admin persona routes.
        app = create_app()
        client = TestClient(app)
        client.post(
            "/admin/users",
            headers=ADMIN_H,
            json={"email": "member@example.com", "role": "user"},
        )
        return client

    def test_bootstrap_seeds_soft_grounded_persona(self):
        client = self._client()
        state = client.get("/admin/persona", headers=ADMIN_H).json()
        self.assertEqual(state["source"], "db")
        self.assertEqual(state["settings"]["template"], "soft-grounded")
        # first agent build already used the seeded persona
        self.assertIsNotNone(self.create_agent_calls[0]["persona"])

    def test_templates_endpoint_lists_all(self):
        client = self._client()
        payload = client.get("/admin/persona/templates", headers=ADMIN_H).json()
        self.assertEqual(
            {t["id"] for t in payload["templates"]},
            {"soft-grounded", "strict", "general"},
        )

    def test_apply_template_rebuilds_agent(self):
        client = self._client()
        builds_before = len(self.create_agent_calls)
        response = client.put(
            "/admin/persona", headers=ADMIN_H, json={"template": "strict"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.create_agent_calls), builds_before + 1)
        persona = self.create_agent_calls[-1]["persona"]
        self.assertIn("ONLY source of knowledge", persona.soul)
        self.assertIn("strictly from the curated source context", self.create_agent_calls[-1]["goal"])

    def test_direct_edit_rebuilds_agent(self):
        client = self._client()
        response = client.put(
            "/admin/persona",
            headers=ADMIN_H,
            json={"soul": "I am a pirate.", "style": "", "agents": "", "goal": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.create_agent_calls[-1]["persona"].soul, "I am a pirate.")

    def test_unknown_template_is_400(self):
        client = self._client()
        response = client.put(
            "/admin/persona", headers=ADMIN_H, json={"template": "nope"}
        )
        self.assertEqual(response.status_code, 400)

    def test_empty_persona_is_400(self):
        client = self._client()
        response = client.put(
            "/admin/persona", headers=ADMIN_H, json={"soul": "", "style": "", "agents": ""}
        )
        self.assertEqual(response.status_code, 400)

    def test_rebuild_failure_keeps_old_agent_serving(self):
        client = self._client()
        self.fail_next_create = True
        response = client.put(
            "/admin/persona", headers=ADMIN_H, json={"template": "general"}
        )
        self.assertEqual(response.status_code, 500)
        self.fail_next_create = False
        # old agent still answers /persona (mock persona from the seed build)
        self.assertEqual(client.get("/persona", headers=ADMIN_H).status_code, 200)

    def test_persona_routes_require_admin(self):
        client = self._client()
        self.assertEqual(client.get("/admin/persona", headers=MEMBER_H).status_code, 403)
        self.assertEqual(
            client.put(
                "/admin/persona", headers=MEMBER_H, json={"template": "general"}
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
