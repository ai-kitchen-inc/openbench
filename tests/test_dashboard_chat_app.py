"""End-to-end FastAPI tests for Dashboard Chat (stub LLM, no network)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

import pytest

DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "examples" / "dashboard-chat" / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))


pytestmark = pytest.mark.integration


def _make_sample_db(directory: Path) -> str:
    import sqlalchemy

    db_path = directory / "app.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text("CREATE TABLE sales (id INTEGER PRIMARY KEY, amount REAL)")
        )
        connection.execute(sqlalchemy.text("INSERT INTO sales (amount) VALUES (10.0), (32.5)"))
    engine.dispose()
    return f"sqlite:///{db_path.as_posix()}"


def _stub_agent():
    """Real BaseAgent wired to a canned LLM so /awp streams without network."""
    from openbench.core.abstractions import LLMProvider, LLMResponse
    from openbench.intelligence.base import BaseAgent

    class StubLLM(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "stub"

        def generate(self, prompt, model, **params):
            return LLMResponse(text="stub reply", model=model, tokens_used=1, cost=0.0)

    agent = BaseAgent(goal="test goal", model="stub-model", max_iterations=2)
    agent._llm = StubLLM()
    return agent


class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The app keeps engines and sqlite stores open for its lifetime;
        # on Windows those file handles make strict cleanup fail.
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(cls._tmp.name)
        cls._env = patch.dict(
            environ,
            {
                "DASHBOARD_CHAT_AUTH_SECRET": "test-secret",
                "DASHBOARD_CHAT_STORAGE_ROOT": str(root / "storage"),
                "DASHBOARD_CHAT_MEMORY_DB": str(root / "memory.db"),
                "GOOGLE_API_KEY": "test-key",
            },
            clear=False,
        )
        cls._env.start()
        cls.db_url = _make_sample_db(root)

        import dashboard_chat.app as app_module
        from fastapi.testclient import TestClient

        cls._agent_patch = patch.object(app_module, "create_agent", _stub_agent)
        cls._agent_patch.start()
        cls.client = TestClient(app_module.create_app())

    @classmethod
    def tearDownClass(cls):
        cls._agent_patch.stop()
        cls._env.stop()
        cls._tmp.cleanup()

    def _headers(self, username: str = "admin", password: str = "admin123") -> dict:
        response = self.client.post(
            "/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_protected_routes_require_token(self):
        for path in ("/db/status", "/dashboard", "/sessions", "/auth/me", "/db/schema"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post("/awp", json={"content": "x"}).status_code, 401)

    def test_bad_login(self):
        response = self.client.post("/auth/login", json={"username": "admin", "password": "no"})
        self.assertEqual(response.status_code, 401)

    def test_connect_status_schema_flow(self):
        headers = self._headers()
        self.assertEqual(self.client.get("/db/status", headers=headers).json()["connected"], False)

        response = self.client.post("/db/connect", json={"url": self.db_url}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["dialect"], "sqlite")
        self.assertIn("sales", response.json()["tables"])

        status = self.client.get("/db/status", headers=headers).json()
        self.assertTrue(status["connected"])
        self.assertEqual(status["tableCount"], 1)

        schema = self.client.get("/db/schema", headers=headers).json()
        self.assertEqual(schema["tables"][0]["name"], "sales")

    def test_connect_rejects_bad_url(self):
        headers = self._headers()
        response = self.client.post("/db/connect", json={"url": "not-a-real-url"}, headers=headers)
        self.assertEqual(response.status_code, 400)

    def test_dashboard_and_panel_data(self):
        import dashboard_chat.app as app_module
        from dashboard_chat.dashboards import build_dashboard_store
        from dashboard_chat.users import storage_root

        headers = self._headers()
        self.client.post("/db/connect", json={"url": self.db_url}, headers=headers)
        self.assertEqual(self.client.get("/dashboard", headers=headers).status_code, 404)

        store = build_dashboard_store(storage_root())
        store.save(
            "admin",
            {
                "title": "Sales",
                "panels": [
                    {
                        "id": "kpi-total",
                        "type": "kpi",
                        "title": "Total",
                        "width": "third",
                        "sql": "SELECT SUM(amount) AS value FROM sales",
                    }
                ],
            },
        )

        spec = self.client.get("/dashboard", headers=headers).json()
        self.assertEqual(spec["title"], "Sales")

        data = self.client.get("/dashboard/panels/kpi-total/data", headers=headers).json()
        self.assertEqual(data["columns"], ["value"])
        self.assertEqual(data["rows"], [[42.5]])

        self.assertEqual(
            self.client.get("/dashboard/panels/nope/data", headers=headers).status_code, 404
        )
        # Guest has no dashboard and no connection: foreign panel ids 404.
        guest_headers = self._headers("guest", "guest123")
        self.assertEqual(
            self.client.get("/dashboard/panels/kpi-total/data", headers=guest_headers).status_code,
            404,
        )
        del app_module  # imported for symmetry with create_app patching

    def test_awp_canonicalizes_session_and_persists_memory(self):
        from openbench.intelligence.memory import SQLiteMemoryStore

        headers = self._headers()
        response = self.client.post(
            "/awp",
            json={"content": "hello", "forwardedProps": {"sessionId": "spoofed-session"}},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("stub reply", body)

        store = SQLiteMemoryStore(db_path=environ["DASHBOARD_CHAT_MEMORY_DB"])
        canonical = store.load("user-admin")
        self.assertTrue(canonical, "expected messages under the canonical session id")
        spoofed = store.load("spoofed-session")
        self.assertFalse(spoofed, "spoofed session id must not receive messages")

        sessions = self.client.get("/sessions", headers=headers).json()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["sessionId"], "user-admin")

    def test_sessions_foreign_id_hidden_and_clear(self):
        headers = self._headers()
        self.client.post("/awp", json={"content": "hi"}, headers=headers)

        guest_headers = self._headers("guest", "guest123")
        self.assertEqual(
            self.client.get("/sessions/user-admin", headers=guest_headers).status_code, 404
        )
        self.assertEqual(
            self.client.delete("/sessions/user-admin", headers=guest_headers).status_code, 404
        )

        self.assertEqual(
            self.client.delete("/sessions/user-admin", headers=headers).status_code, 200
        )
        self.assertEqual(self.client.get("/sessions", headers=headers).json(), [])

    def test_admin_user_crud(self):
        headers = self._headers()
        response = self.client.post(
            "/admin/users",
            json={"username": "dana", "password": "secret1", "role": "guest"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        names = {
            user["username"] for user in self.client.get("/admin/users", headers=headers).json()
        }
        self.assertIn("dana", names)

        guest_headers = self._headers("dana", "secret1")
        self.assertEqual(self.client.get("/admin/users", headers=guest_headers).status_code, 403)

        self.assertEqual(self.client.delete("/admin/users/dana", headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
