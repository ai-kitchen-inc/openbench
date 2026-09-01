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

from general_chat.server.custom_functions import CustomFunctionStore  # noqa: E402
from general_chat.server.custom_skills import CustomSkillError, CustomSkillStore  # noqa: E402

ADMIN = FirebaseUser(uid="admin-1", email="boss@example.com")
ADMIN_H = {"Authorization": "Bearer token-admin"}


class TestCustomSkillStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env_patch = patch.dict(
            environ,
            {"GENERAL_CHAT_CUSTOM_SKILLS_DIR": "", "CUSTOM_FN_DATA_PATH": ""},
        )
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

    def test_save_from_prompt_generates_unique_markdown(self):
        first = self.store.save_from_prompt(
            "Buat skill untuk review kontrak vendor. Agent harus menilai klausul risiko, "
            "kewajiban, dan rekomendasi negosiasi."
        )
        second = self.store.save_from_prompt(
            "Buat skill untuk review kontrak vendor. Agent harus menilai klausul risiko."
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(first["id"].startswith("review-kontrak-vendor"))
        self.assertIn("## Instructions", first["skill_md"])
        self.assertIn("## Triggers", first["skill_md"])

    def test_save_from_prompt_reuses_existing_custom_function(self):
        functions = CustomFunctionStore(self._tmp.name)
        functions.save(
            "custom_skill_image_brief",
            "\n".join(
                [
                    "def custom_skill_image_brief(project_description):",
                    "    return {",
                    "        'computed_by': 'custom_skill_image_brief',",
                    "        'prompt': project_description,",
                    "    }",
                ]
            ),
            "Existing image brief function.",
        )

        saved = self.store.save_from_prompt(
            "Buat skill rancangan proyek pembangunan yang juga butuh gambar visual.",
            custom_functions=functions,
        )

        tooling = saved["tooling"]
        self.assertEqual(tooling["created_functions"], [])
        self.assertEqual(tooling["required"][0]["name"], "custom_skill_image_brief")
        self.assertEqual(tooling["required"][0]["type"], "custom_function")
        self.assertIn("## Tooling", saved["skill_md"])
        self.assertIn("custom_function_run_function", saved["skill_md"])

    def test_save_from_prompt_reuses_manual_function_by_semantic_name(self):
        functions = CustomFunctionStore(self._tmp.name)
        functions.save(
            "add",
            "\n".join(
                [
                    "def add(a, b):",
                    "    return {'computed_by': 'add', 'result': float(a) + float(b)}",
                ]
            ),
            "Menjumlahkan dua angka.",
        )

        saved = self.store.save_from_prompt(
            "Buat skill untuk menghitung penjumlahan dua angka. Saat user memberi "
            "dua angka, hasil harus akurat dan konsisten.",
            custom_functions=functions,
        )

        tooling = saved["tooling"]
        self.assertEqual(tooling["created_functions"], [])
        self.assertEqual(tooling["required"][0]["name"], "add")
        self.assertIn('name="add"', saved["skill_md"])

    def test_save_from_prompt_creates_missing_custom_function(self):
        functions = CustomFunctionStore(self._tmp.name)

        saved = self.store.save_from_prompt(
            "Buat skill estimasi anggaran proyek pembangunan dari bahan baku dan biaya.",
            custom_functions=functions,
        )

        tooling = saved["tooling"]
        self.assertEqual(tooling["created_functions"][0]["name"], "custom_skill_estimate_budget")
        self.assertTrue((functions.root / "custom_skill_estimate_budget.py").is_file())
        self.assertIn("custom_skill_estimate_budget", saved["skill_md"])

    def test_save_from_prompt_recommends_function_for_plain_calculation_prompt(self):
        functions = CustomFunctionStore(self._tmp.name)

        saved = self.store.save_from_prompt(
            "Buat skill untuk menghitung luas bangunan persegi panjang. Saat user "
            "memberikan panjang dan lebar tanah, berikan hasil luas yang akurat "
            "dan konsisten.",
            custom_functions=functions,
        )

        tooling = saved["tooling"]
        self.assertEqual(tooling["created_functions"][0]["name"], "hitung_luas_bangunan")
        self.assertTrue((functions.root / "hitung_luas_bangunan.py").is_file())
        self.assertIn('name="hitung_luas_bangunan"', saved["skill_md"])

    def test_save_from_prompt_creates_explicit_named_custom_function(self):
        functions = CustomFunctionStore(self._tmp.name)

        saved = self.store.save_from_prompt(
            "Saya ingin membuat skill menghitung luas bangunan berbentuk persegi panjang "
            "ketika user melampirkan panjang dan lebar tanah. Perhitungan harus membuat "
            "fungsi kustom dengan nama fungsi luas_bangunan.",
            custom_functions=functions,
        )

        tooling = saved["tooling"]
        self.assertEqual(tooling["created_functions"][0]["name"], "luas_bangunan")
        self.assertTrue((functions.root / "luas_bangunan.py").is_file())
        code = (functions.root / "luas_bangunan.py").read_text(encoding="utf-8")
        self.assertIn("def luas_bangunan", code)
        self.assertIn("panjang_value * lebar_value", code)

    def test_save_from_prompt_keeps_plain_guidance_skill_knowledge_only(self):
        functions = CustomFunctionStore(self._tmp.name)

        saved = self.store.save_from_prompt(
            "Buat skill untuk membantu menulis balasan customer service dengan nada "
            "ramah, singkat, dan profesional.",
            custom_functions=functions,
        )

        self.assertEqual(saved["tooling"]["required"], [])
        self.assertEqual(functions.names(), set())

    def test_save_from_prompt_reuses_matching_mcp_tool_before_creating_function(self):
        class FakeMCPRegistry:
            def list_payload(self):
                return {
                    "servers": [
                        {
                            "id": "image-server",
                            "name": "image",
                            "enabled": True,
                            "tools": [
                                {
                                    "name": "generate_image",
                                    "registered_tool_name": "image_generate_image",
                                    "description": "Generate image previews",
                                    "enabled": True,
                                }
                            ],
                        }
                    ]
                }

        functions = CustomFunctionStore(self._tmp.name)
        saved = self.store.save_from_prompt(
            "Buat skill kampanye yang perlu generate image untuk poster.",
            custom_functions=functions,
            mcp_registry=FakeMCPRegistry(),
        )

        tooling = saved["tooling"]
        self.assertEqual(tooling["created_functions"], [])
        self.assertEqual(tooling["required"][0]["type"], "mcp")
        self.assertEqual(tooling["required"][0]["name"], "image_generate_image")
        self.assertFalse((functions.root / "custom_skill_image_brief.py").exists())

    def test_save_markdown_updates_metadata_from_skill_md(self):
        saved = self.store.save_from_prompt("Buat skill untuk review risiko.")
        updated = self.store.save_markdown(
            saved["id"],
            "\n".join(
                [
                    "# Audit SOP",
                    "",
                    "Membantu audit internal.",
                    "",
                    "## Triggers",
                    "",
                    "- audit internal",
                    "",
                    "## Instructions",
                    "",
                    "Selalu susun temuan dan rekomendasi.",
                    "",
                    "## Version",
                    "",
                    "0.2.0",
                ]
            ),
        )
        self.assertEqual(updated["id"], saved["id"])
        self.assertEqual(updated["name"], "Audit SOP")
        self.assertEqual(updated["version"], "0.2.0")
        self.assertEqual(updated["triggers"], ["audit internal"])
        self.assertIn("Selalu susun", updated["instructions"])


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
                "prompt": (
                    "Buat skill untuk risk review. Return a table with risk, impact, "
                    "mitigation, and owner."
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        created_id = response.json()["id"]
        self.assertTrue(created_id)
        self.assertEqual(len(self.create_agent_calls), builds_before + 1)
        loaded_paths = self.create_agent_calls[-1]["custom_skill_paths"]
        self.assertEqual(len(loaded_paths), 1)
        self.assertTrue((Path(loaded_paths[0]) / "SKILL.md").is_file())

        listed = client.get("/admin/custom-skills", headers=ADMIN_H)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([skill["id"] for skill in listed.json()["skills"]], [created_id])

        edited = client.post(
            "/admin/custom-skills",
            headers=ADMIN_H,
            json={
                "id": created_id,
                "skill_md": "# Risk Review\n\nUpdated.\n\n## Version\n\n0.1.1",
            },
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["name"], "Risk Review")

        deleted = client.delete(f"/admin/custom-skills/{created_id}", headers=ADMIN_H)
        self.assertEqual(deleted.status_code, 200)
        second_delete = client.delete(f"/admin/custom-skills/{created_id}", headers=ADMIN_H)
        self.assertEqual(second_delete.status_code, 404)

    def test_save_validation_errors_are_400(self):
        client = self._client()
        response = client.post(
            "/admin/custom-skills",
            headers=ADMIN_H,
            json={"prompt": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("prompt is required", response.json()["detail"])

    def test_prompt_route_can_create_custom_function_dependency(self):
        client = self._client()
        response = client.post(
            "/admin/custom-skills",
            headers=ADMIN_H,
            json={
                "prompt": (
                    "Buat skill untuk menghitung luas bangunan persegi panjang. Saat user "
                    "memberikan panjang dan lebar tanah, berikan hasil luas yang akurat "
                    "dan konsisten."
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["tooling"]["created_functions"][0]["name"],
            "hitung_luas_bangunan",
        )
        self.assertIn('name="hitung_luas_bangunan"', payload["skill_md"])


if __name__ == "__main__":
    unittest.main()
