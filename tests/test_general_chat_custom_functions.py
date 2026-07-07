"""Tests for the general-chat custom-functions store + routes."""

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

from general_chat.server.custom_functions import (  # noqa: E402
    CustomFunctionError,
    CustomFunctionStore,
)

pytestmark = pytest.mark.integration

_ADD_CODE = "def add(a, b):\n    return a + b\n"


class TestCustomFunctionStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Ensure the env override does not leak in from the host.
        env_patch = patch.dict(environ, {"CUSTOM_FN_DATA_PATH": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.store = CustomFunctionStore(self._tmp.name)

    def test_save_list_delete_round_trip(self):
        meta = self.store.save("add", _ADD_CODE, "adds two numbers")
        self.assertEqual(meta["name"], "add")
        listed = self.store.list()
        self.assertEqual([m["name"] for m in listed], ["add"])
        self.assertIn("def add", listed[0]["code"])
        self.assertTrue(self.store.delete("add"))
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.store.delete("add"))

    def test_save_rejects_bad_name(self):
        for bad in ("", "1x", "Has-Upper", "../x"):
            with self.assertRaises(CustomFunctionError, msg=bad):
                self.store.save(bad, _ADD_CODE)

    def test_save_rejects_syntax_error(self):
        with self.assertRaises(CustomFunctionError):
            self.store.save("add", "def add(a, b:\n    return a\n")

    def test_save_rejects_zero_or_many_functions(self):
        with self.assertRaises(CustomFunctionError):
            self.store.save("add", "x = 1\n")
        with self.assertRaises(CustomFunctionError):
            self.store.save("add", "def add():\n    pass\n\ndef sub():\n    pass\n")

    def test_save_rejects_name_mismatch(self):
        with self.assertRaises(CustomFunctionError):
            self.store.save("add", "def subtract(a, b):\n    return a - b\n")

    def test_save_rejects_oversized_code(self):
        big = "def add(a, b):\n    return a + b\n" + ("# pad\n" * 20000)
        with self.assertRaises(CustomFunctionError):
            self.store.save("add", big)

    def test_helpers_allowed_around_single_function(self):
        code = "import math\n\nLIMIT = 10\n\ndef add(a, b):\n    return min(a + b, LIMIT)\n"
        meta = self.store.save("add", code)
        self.assertEqual(meta["name"], "add")

    def test_test_run_missing_function_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.store.test_run("ghost", {})


class TestCustomFunctionRoutes(unittest.TestCase):
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
                    "GENERAL_CHAT_ALLOWED_EMAILS": "allowed@example.com",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                    "CUSTOM_FN_DATA_PATH": str(tmpdir / "functions"),
                },
                clear=False,
            )
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)

        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))

        verifier = Mock()
        verifier.verify.return_value = FirebaseUser(uid="user-1", email="allowed@example.com")
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": "Bearer good"}

    def test_routes_require_auth(self):
        client = self._client()
        self.assertEqual(client.get("/functions").status_code, 401)
        self.assertEqual(
            client.post("/functions", json={"name": "add", "code": _ADD_CODE}).status_code, 401
        )

    def test_save_list_delete_flow(self):
        client = self._client()
        saved = client.post(
            "/functions",
            json={"name": "add", "code": _ADD_CODE, "description": "adds"},
            headers=self._auth,
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["name"], "add")

        listed = client.get("/functions", headers=self._auth)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([f["name"] for f in listed.json()["functions"]], ["add"])

        deleted = client.delete("/functions/add", headers=self._auth)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.delete("/functions/add", headers=self._auth).status_code, 404)

    def test_save_validation_errors_are_400(self):
        client = self._client()
        bad = client.post(
            "/functions", json={"name": "add", "code": "x = 1\n"}, headers=self._auth
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("exactly one top-level function", bad.json()["detail"])

    def test_test_run_route_uses_sandbox(self):
        client = self._client()
        client.post(
            "/functions", json={"name": "add", "code": _ADD_CODE}, headers=self._auth
        )
        with patch(
            "general_chat.server.custom_functions.CustomFunctionStore.test_run",
            return_value={"ok": True, "result": 5, "stdout": ""},
        ) as mock_run:
            response = client.post(
                "/functions/add/run", json={"kwargs": {"a": 2, "b": 3}}, headers=self._auth
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], 5)
        mock_run.assert_called_once_with("add", {"a": 2, "b": 3})

    def test_test_run_unknown_function_is_404(self):
        client = self._client()
        response = client.post("/functions/ghost/run", json={}, headers=self._auth)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
