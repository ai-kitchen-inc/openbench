"""Tests for dashboard publish + Grafana export in General Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.grafana import view_model_to_grafana  # noqa: E402

_VIEW_MODEL = {
    "title": "Sales Dashboard",
    "description": "Quarterly overview",
    "datasets": {
        "by_region": [
            {"region": "EU", "revenue": 1200, "orders": 45},
            {"region": "NA", "revenue": 3400, "orders": 120},
        ]
    },
    "kpis": [{"label": "Total Revenue", "value": 4600, "unit": "currencyUSD"}],
    "sections": [
        {
            "title": "Performance",
            "items": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Revenue by Region",
                    "dataset": "by_region",
                    "x": "region",
                    "y": "revenue",
                },
                {
                    "type": "table",
                    "title": "Region Detail",
                    "dataset": "by_region",
                    "columns": [
                        {"key": "region", "label": "Region"},
                        {"key": "revenue", "label": "Revenue"},
                    ],
                },
                {"type": "text", "title": "Notes", "content": "Strong NA quarter."},
            ],
        }
    ],
}


pytestmark = pytest.mark.integration


class TestGrafanaConverter(unittest.TestCase):
    def setUp(self) -> None:
        self.model = view_model_to_grafana(_VIEW_MODEL)
        self.by_type = self._panels_by_type(self.model["panels"])

    @staticmethod
    def _panels_by_type(panels: list[dict]) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for panel in panels:
            result.setdefault(panel["type"], []).append(panel)
        return result

    def test_dashboard_envelope(self):
        self.assertEqual(self.model["title"], "Sales Dashboard")
        self.assertEqual(self.model["schemaVersion"], 39)
        self.assertIsNone(self.model["uid"])
        self.assertTrue(self.model["__inputs"])
        self.assertEqual(self.model["__inputs"][0]["pluginId"], "grafana-testdata-datasource")

    def test_kpi_maps_to_stat(self):
        self.assertIn("stat", self.by_type)
        stat = self.by_type["stat"][0]
        self.assertEqual(stat["title"], "Total Revenue")
        self.assertEqual(stat["fieldConfig"]["defaults"]["unit"], "currencyUSD")

    def test_chart_maps_to_barchart_with_embedded_csv(self):
        self.assertIn("barchart", self.by_type)
        bar = self.by_type["barchart"][0]
        self.assertEqual(bar["options"]["xField"], "region")
        csv = bar["targets"][0]["csvContent"]
        self.assertEqual(csv.splitlines()[0], "region,revenue")
        self.assertIn("EU,1200", csv)
        self.assertEqual(bar["targets"][0]["scenarioId"], "csv_content")
        self.assertEqual(bar["targets"][0]["datasource"]["type"], "grafana-testdata-datasource")

    def test_chart_type_mapping(self):
        cases = {
            "line": "timeseries",
            "area": "timeseries",
            "pie": "piechart",
            "scatter": "xychart",
            "bar": "barchart",
        }
        for chart_type, expected in cases.items():
            vm = {
                "title": "t",
                "sections": [
                    {
                        "items": [
                            {
                                "type": "chart",
                                "chart_type": chart_type,
                                "data": [{"x": "a", "y": 1}],
                                "x": "x",
                                "y": "y",
                            }
                        ]
                    }
                ],
            }
            panels = [p for p in view_model_to_grafana(vm)["panels"] if p["type"] != "row"]
            self.assertEqual(panels[0]["type"], expected, chart_type)

    def test_table_and_text_panels(self):
        self.assertIn("table", self.by_type)
        self.assertEqual(
            self.by_type["table"][0]["targets"][0]["csvContent"].splitlines()[0],
            "region,revenue",
        )
        self.assertIn("text", self.by_type)
        self.assertEqual(self.by_type["text"][0]["options"]["content"], "Strong NA quarter.")

    def test_grid_positions_valid(self):
        for panel in self.model["panels"]:
            pos = panel["gridPos"]
            self.assertGreaterEqual(pos["x"], 0)
            self.assertLessEqual(pos["x"] + pos["w"], 24)
            self.assertGreater(pos["h"], 0)

    def test_empty_view_model(self):
        model = view_model_to_grafana({})
        self.assertEqual(model["panels"], [])
        self.assertEqual(model["schemaVersion"], 39)

    def test_csv_escapes_special_chars(self):
        vm = {
            "sections": [
                {
                    "items": [
                        {
                            "type": "table",
                            "data": [{"name": "a,b", "note": 'has "quote"'}],
                        }
                    ]
                }
            ]
        }
        csv = view_model_to_grafana(vm)["panels"][0]["targets"][0]["csvContent"]
        self.assertIn('"a,b"', csv)
        self.assertIn('"has ""quote"""', csv)


class TestDashboardRoutes(unittest.TestCase):
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

    def test_export_grafana_requires_auth(self):
        client = self._client()
        response = client.post("/dashboard/export/grafana", json={"viewModel": _VIEW_MODEL})
        self.assertEqual(response.status_code, 401)

    def test_export_grafana_returns_model(self):
        client = self._client()
        response = client.post(
            "/dashboard/export/grafana",
            json={"viewModel": _VIEW_MODEL},
            headers=self._auth,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schemaVersion"], 39)
        self.assertTrue(body["panels"])

    def test_export_grafana_rejects_empty(self):
        client = self._client()
        response = client.post("/dashboard/export/grafana", json={}, headers=self._auth)
        self.assertEqual(response.status_code, 400)

    def test_publish_then_public_view(self):
        client = self._client()
        published = client.post(
            "/dashboard/publish", json={"viewModel": _VIEW_MODEL}, headers=self._auth
        )
        self.assertEqual(published.status_code, 200)
        payload = published.json()
        dashboard_id = payload["id"]
        self.assertTrue(payload["url"].endswith(f"/d/{dashboard_id}"))

        # PUBLIC: no auth header, auth is enabled — must still render.
        viewed = client.get(f"/d/{dashboard_id}")
        self.assertEqual(viewed.status_code, 200)
        self.assertIn("text/html", viewed.headers["content-type"])
        self.assertIn("Sales Dashboard", viewed.text)

    def test_export_pdf_requires_auth(self):
        client = self._client()
        response = client.post("/dashboard/export/pdf", json={"viewModel": _VIEW_MODEL})
        self.assertEqual(response.status_code, 401)

    def test_export_pdf_rejects_empty(self):
        client = self._client()
        response = client.post("/dashboard/export/pdf", json={}, headers=self._auth)
        self.assertEqual(response.status_code, 400)

    def test_export_pdf_returns_pdf(self):
        client = self._client()
        # Render is mocked so the test never launches Chromium.
        with patch(
            "general_chat.server.app.render_dashboard_pdf",
            new=AsyncMock(return_value=b"%PDF-1.4 fake"),
        ):
            response = client.post(
                "/dashboard/export/pdf",
                json={"viewModel": _VIEW_MODEL},
                headers=self._auth,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("sales-dashboard.pdf", response.headers["content-disposition"])
        self.assertEqual(response.content, b"%PDF-1.4 fake")

    def test_export_pdf_tolerates_duplicated_body(self):
        # Reproduces the Starlette BaseHTTPMiddleware + keep-alive quirk where a
        # second copy of the body is appended; the endpoint must parse the first
        # JSON value and ignore the trailing duplicate instead of 500-ing.
        client = self._client()
        import json as _json

        one = _json.dumps({"viewModel": _VIEW_MODEL})
        with patch(
            "general_chat.server.app.render_dashboard_pdf",
            new=AsyncMock(return_value=b"%PDF-1.4 fake"),
        ):
            response = client.post(
                "/dashboard/export/pdf",
                content=(one + one).encode("utf-8"),
                headers={**self._auth, "Content-Type": "application/json"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-1.4 fake")

    def test_unknown_dashboard_id_is_404(self):
        client = self._client()
        self.assertEqual(client.get("/d/abcdef012345").status_code, 404)

    def test_non_hex_id_is_404(self):
        client = self._client()
        self.assertEqual(client.get("/d/not-a-valid-id").status_code, 404)


if __name__ == "__main__":
    unittest.main()
