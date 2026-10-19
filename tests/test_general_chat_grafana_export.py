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

from general_chat.live_dashboard import LiveDashboardRecord, LiveQuery  # noqa: E402
from general_chat.server.grafana import (  # noqa: E402
    live_dashboard_to_grafana,
    partition_datasets,
    view_model_to_grafana,
)

_LIVE_QUERIES = {
    "by_region": LiveQuery(
        sql="SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region;", max_rows=500
    ),
    "by_day": LiveQuery(
        sql="SELECT day, SUM(revenue) AS revenue FROM sales GROUP BY day", max_rows=90
    ),
    "total": LiveQuery(sql="SELECT SUM(revenue) AS total FROM sales", max_rows=1),
}
_LIVE_TEMPLATE = {
    "kpis": [
        {
            "label": "Total Pendapatan",
            "dataset": "total",
            "value_column": "total",
            "unit": "currencyUSD",
        }
    ],
    "sections": [
        {
            "title": "Ringkasan",
            "items": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Per wilayah",
                    "dataset": "by_region",
                    "x_field": "region",
                    "y_field": "revenue",
                },
                {
                    "type": "chart",
                    "chart_type": "line",
                    "title": "Harian",
                    "dataset": "by_day",
                    "x_field": "day",
                    "y_field": "revenue",
                },
                {
                    "type": "table",
                    "title": "Tabel",
                    "dataset": "by_region",
                    "columns": ["region", "revenue"],
                },
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Statis",
                    "data": [{"k": "a", "v": 1}],
                    "x_field": "k",
                    "y_field": "v",
                },
            ],
        }
    ],
}


def _live_record(**overrides) -> LiveDashboardRecord:
    base = {
        "id": "abcdef123456",
        "owner": "allowed@example.com",
        "title": "Penjualan Live",
        "description": "Uji",
        "server_id": "server-db",
        "queries": dict(_LIVE_QUERIES),
        "template": _LIVE_TEMPLATE,
        "refresh_interval_seconds": 30,
        "snapshot": {
            "datasets": {
                "by_region": [{"region": "Jawa", "revenue": 10}],
                "by_day": [{"day": "2026-10-19", "revenue": 10}],
                "total": [{"total": 10}],
            },
            "viewModel": {"title": "Penjualan Live"},
        },
    }
    base.update(overrides)
    return LiveDashboardRecord(**base)


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
        # line/area use date x values — categorical x falls back to barchart
        # (see TestGrafanaTimeseriesFallback).
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
                                "data": [{"x": "2026-06-01", "y": 1}],
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


class TestGrafanaRendererParity(unittest.TestCase):
    """Exporter must resolve KPI values and x/y aliases like the renderers."""

    def test_kpi_value_derived_from_dataset_first_row(self):
        vm = {
            "datasets": {"summary": [{"total_revenue": 115431.58, "tx": 3636}]},
            "kpis": [
                {"label": "Total Revenue", "dataset_id": "summary", "value_column": "total_revenue"}
            ],
        }
        stat = view_model_to_grafana(vm)["panels"][0]
        self.assertIn("115431.58", stat["targets"][0]["csvContent"])

    def test_kpi_value_dataset_alias_and_column_alias(self):
        vm = {
            "datasets": {"summary": [{"count": 42}]},
            "kpis": [{"label": "Count", "dataset": "summary", "field": "count"}],
        }
        stat = view_model_to_grafana(vm)["panels"][0]
        self.assertIn("42", stat["targets"][0]["csvContent"])

    def test_kpi_formatted_string_coerced_to_number(self):
        vm = {"kpis": [{"label": "Revenue", "value": "$115,431.58"}]}
        stat = view_model_to_grafana(vm)["panels"][0]
        csv = stat["targets"][0]["csvContent"]
        self.assertIn("115431.58", csv)
        self.assertNotIn("$", csv)

    def test_kpi_unparseable_string_passes_through(self):
        vm = {"kpis": [{"label": "Status", "value": "healthy"}]}
        stat = view_model_to_grafana(vm)["panels"][0]
        self.assertIn("healthy", stat["targets"][0]["csvContent"])

    def test_chart_x_axis_and_y_axis_aliases(self):
        vm = {
            "sections": [
                {
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "data": [{"month": "Feb", "revenue": 6398.86}],
                            "x_axis": "month",
                            "y_axis": "revenue",
                        }
                    ]
                }
            ]
        }
        panel = [p for p in view_model_to_grafana(vm)["panels"] if p["type"] != "row"][0]
        self.assertEqual(panel["targets"][0]["csvContent"].splitlines()[0], "month,revenue")

    def test_section_item_aliases(self):
        # Renderers accept items|components|widgets|panels|charts|cards —
        # the exporter must too (a miss deploys empty rows).
        chart = {
            "type": "chart",
            "chart_type": "bar",
            "title": "T",
            "data": [{"name": "a", "v": 1}],
            "x": "name",
            "y": "v",
        }
        for alias in ("items", "components", "widgets", "panels", "charts", "cards"):
            vm = {"sections": [{"title": "S", alias: [chart]}]}
            types = [p["type"] for p in view_model_to_grafana(vm)["panels"]]
            self.assertEqual(types, ["row", "barchart"], alias)

    def test_kpi_stat_field_regex_not_broken_by_display_name(self):
        # Grafana matches reduceOptions.fields against DISPLAY names; setting
        # fieldConfig.defaults.displayName renames the 'value' field and the
        # /^value$/ regex stops matching -> stat shows "No data". Guard it.
        vm = {"kpis": [{"label": "Total Revenue", "value": 42}]}
        stat = view_model_to_grafana(vm)["panels"][0]
        self.assertNotIn("displayName", stat["fieldConfig"]["defaults"])
        self.assertEqual(stat["options"]["reduceOptions"]["fields"], "/^value$/")
        self.assertEqual(stat["options"]["textMode"], "value")

    def test_x_fallback_prefers_category_column(self):
        # Numeric column first — the renderers pick the first NON-numeric column.
        vm = {
            "sections": [
                {
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "data": [{"revenue": 6398.86, "month": "Feb"}],
                        }
                    ]
                }
            ]
        }
        panel = [p for p in view_model_to_grafana(vm)["panels"] if p["type"] != "row"][0]
        self.assertEqual(panel["targets"][0]["csvContent"].splitlines()[0], "month,revenue")


class TestGrafanaTimeseriesFallback(unittest.TestCase):
    """line/area only map to timeseries when x is temporal."""

    @staticmethod
    def _panel(vm: dict) -> dict:
        return [p for p in view_model_to_grafana(vm)["panels"] if p["type"] != "row"][0]

    @staticmethod
    def _line_vm(data: list[dict], **item_extra) -> dict:
        item = {"type": "chart", "chart_type": "line", "data": data, **item_extra}
        return {"sections": [{"items": [item]}]}

    def test_month_names_fall_back_to_barchart(self):
        panel = self._panel(
            self._line_vm([{"month": "Feb", "revenue": 1.0}], x="month", y="revenue")
        )
        self.assertEqual(panel["type"], "barchart")
        self.assertEqual(panel["options"]["xField"], "month")

    def test_iso_dates_keep_timeseries(self):
        panel = self._panel(
            self._line_vm(
                [{"day": "2026-06-01", "revenue": 1.0}, {"day": "2026-06-02", "revenue": 2.0}],
                x="day",
                y="revenue",
            )
        )
        self.assertEqual(panel["type"], "timeseries")

    def test_year_month_keeps_timeseries(self):
        panel = self._panel(
            self._line_vm([{"month": "2026-06", "revenue": 1.0}], x="month", y="revenue")
        )
        self.assertEqual(panel["type"], "timeseries")

    def test_epoch_values_keep_timeseries(self):
        panel = self._panel(
            self._line_vm([{"ts": 1750000000, "revenue": 1.0}], x="ts", y="revenue")
        )
        self.assertEqual(panel["type"], "timeseries")

    def test_live_table_without_records_uses_key_name_heuristic(self):
        live = {"tables": {"trend": "mart.trend"}, "pg_uid": "pg", "testdata_uid": "td"}
        base = {
            "datasets": {"trend": []},
            "sections": [
                {
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "line",
                            "dataset": "trend",
                            "x": "order_date",
                            "y": "revenue",
                        }
                    ]
                }
            ],
        }
        panel = [p for p in view_model_to_grafana(base, live=live)["panels"] if p["type"] != "row"][
            0
        ]
        self.assertEqual(panel["type"], "timeseries")

        base["sections"][0]["items"][0]["x"] = "category"
        panel = [p for p in view_model_to_grafana(base, live=live)["panels"] if p["type"] != "row"][
            0
        ]
        self.assertEqual(panel["type"], "barchart")


class TestGrafanaLiveMode(unittest.TestCase):
    """Deploy-mode (`live=`) targets concrete datasource UIDs."""

    _LIVE = {
        "tables": {"by_region": "public.by_region"},
        "pg_uid": "appdata-postgres",
        "testdata_uid": "testdata",
    }

    def setUp(self) -> None:
        self.model = view_model_to_grafana(_VIEW_MODEL, live=self._LIVE)
        self.panels = [p for p in self.model["panels"] if p["type"] != "row"]

    def test_no_import_inputs_in_live_mode(self):
        self.assertNotIn("__inputs", self.model)
        self.assertNotIn("__requires", self.model)

    def test_table_backed_dataset_becomes_postgres_sql(self):
        bar = next(p for p in self.panels if p["type"] == "barchart")
        self.assertEqual(bar["datasource"]["uid"], "appdata-postgres")
        target = bar["targets"][0]
        self.assertEqual(target["format"], "table")
        self.assertEqual(
            target["rawSql"],
            'SELECT "region", "revenue" FROM public.by_region LIMIT 1000',
        )

    def test_kpi_stays_inline_with_concrete_uid(self):
        stat = next(p for p in self.panels if p["type"] == "stat")
        self.assertEqual(stat["datasource"]["uid"], "testdata")
        self.assertEqual(stat["targets"][0]["scenarioId"], "csv_content")

    def test_inline_item_data_stays_csv(self):
        vm = {
            "sections": [
                {
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "data": [{"x": "a", "y": 1}],
                            "x": "x",
                            "y": "y",
                        }
                    ]
                }
            ]
        }
        panels = [
            p for p in view_model_to_grafana(vm, live=self._LIVE)["panels"] if p["type"] != "row"
        ]
        self.assertEqual(panels[0]["targets"][0]["scenarioId"], "csv_content")
        self.assertEqual(panels[0]["datasource"]["uid"], "testdata")

    def test_unsafe_table_name_falls_back_to_csv(self):
        live = {**self._LIVE, "tables": {"by_region": 'public."x"; DROP TABLE y'}}
        model = view_model_to_grafana(_VIEW_MODEL, live=live)
        bar = next(p for p in model["panels"] if p["type"] == "barchart")
        self.assertEqual(bar["targets"][0].get("scenarioId"), "csv_content")

    def test_unsafe_column_falls_back_to_csv(self):
        vm = {
            "datasets": {"by_region": [{'a"b': 1, "region": "EU"}]},
            "sections": [{"items": [{"type": "table", "dataset": "by_region"}]}],
        }
        model = view_model_to_grafana(vm, live=self._LIVE)
        table = next(p for p in model["panels"] if p["type"] == "table")
        self.assertEqual(table["targets"][0].get("scenarioId"), "csv_content")

    def test_partition_datasets(self):
        vm = {"datasets": {"by_region": [], "computed": [{"a": 1}]}}
        live, inline = partition_datasets(vm, {"by_region": "public.by_region"})
        self.assertEqual(live, ["by_region"])
        self.assertEqual(inline, ["computed"])


class TestGrafanaLiveRecord(unittest.TestCase):
    """Live (database-bound) records become self-refreshing SQL panels."""

    def _panels(self, model):
        return {p["title"]: p for p in model["panels"] if p["type"] != "row"}

    def test_export_mode_uses_subquery_sql_and_appdata_input(self):
        model = live_dashboard_to_grafana(_live_record())
        panels = self._panels(model)
        bar = panels["Per wilayah"]
        target = bar["targets"][0]
        self.assertEqual(
            target["rawSql"],
            'SELECT "region", "revenue" FROM (SELECT region, SUM(revenue) AS revenue '
            "FROM sales GROUP BY region) AS q LIMIT 500",
        )
        self.assertEqual(target["format"], "table")
        self.assertEqual(
            bar["datasource"], {"type": "grafana-postgresql-datasource", "uid": "${DS_APPDATA}"}
        )
        self.assertEqual(bar["type"], "barchart")
        self.assertEqual(bar["options"]["xField"], "region")
        self.assertEqual(model["refresh"], "30s")
        self.assertEqual([i["name"] for i in model["__inputs"]], ["DS_TESTDATA", "DS_APPDATA"])
        self.assertIn("grafana-postgresql-datasource", [r["id"] for r in model["__requires"]])
        self.assertEqual(model["title"], "Penjualan Live")

    def test_kpi_runs_query_with_value_alias(self):
        panels = self._panels(live_dashboard_to_grafana(_live_record()))
        kpi = panels["Total Pendapatan"]
        self.assertEqual(kpi["type"], "stat")
        self.assertEqual(
            kpi["targets"][0]["rawSql"],
            'SELECT "total" AS value FROM (SELECT SUM(revenue) AS total FROM sales) AS q LIMIT 1',
        )
        self.assertEqual(kpi["options"]["reduceOptions"]["fields"], "/^value$/")
        self.assertNotIn("displayName", kpi["fieldConfig"]["defaults"])
        self.assertEqual(kpi["fieldConfig"]["defaults"]["unit"], "currencyUSD")

    def test_line_chart_keeps_timeseries_when_snapshot_x_is_temporal(self):
        panels = self._panels(live_dashboard_to_grafana(_live_record()))
        line = panels["Harian"]
        self.assertEqual(line["type"], "timeseries")
        self.assertIn(
            "FROM (SELECT day, SUM(revenue) AS revenue FROM sales GROUP BY day) AS q LIMIT 90",
            line["targets"][0]["rawSql"],
        )

    def test_table_and_static_items(self):
        panels = self._panels(live_dashboard_to_grafana(_live_record()))
        table = panels["Tabel"]
        self.assertEqual(
            table["targets"][0]["rawSql"].split(" FROM ")[0], 'SELECT "region", "revenue"'
        )
        static = panels["Statis"]
        self.assertEqual(static["targets"][0]["scenarioId"], "csv_content")
        self.assertEqual(static["datasource"]["uid"], "${DS_TESTDATA}")

    def test_deploy_mode_targets_concrete_uid_without_inputs(self):
        model = live_dashboard_to_grafana(
            _live_record(),
            live={"tables": {}, "pg_uid": "appdata-postgres", "testdata_uid": "testdata"},
        )
        self.assertNotIn("__inputs", model)
        bar = self._panels(model)["Per wilayah"]
        self.assertEqual(bar["datasource"]["uid"], "appdata-postgres")
        self.assertEqual(model["refresh"], "30s")

    def test_manual_interval_has_no_refresh(self):
        model = live_dashboard_to_grafana(_live_record(refresh_interval_seconds=0))
        self.assertNotIn("refresh", model)

    def test_unsafe_column_falls_back_to_csv(self):
        template = {
            "sections": [
                {
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Bad",
                            "dataset": "by_region",
                            "x_field": 'reg"ion',
                            "y_field": "revenue",
                        }
                    ]
                }
            ]
        }
        panels = self._panels(live_dashboard_to_grafana(_live_record(template=template)))
        self.assertEqual(panels["Bad"]["targets"][0]["scenarioId"], "csv_content")

    def test_static_view_model_honours_x_field_y_field(self):
        view_model = {
            "title": "S",
            "datasets": {"d": [{"month": "Jan", "a": 1, "b": 2}]},
            "sections": [
                {
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Multi",
                            "dataset": "d",
                            "x_field": "month",
                            "y_fields": ["a", "b"],
                        }
                    ]
                }
            ],
        }
        panel = self._panels(view_model_to_grafana(view_model))["Multi"]
        self.assertEqual(panel["options"]["xField"], "month")
        self.assertEqual(panel["targets"][0]["csvContent"].splitlines()[0], "month,a,b")


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

    def test_deploy_grafana_requires_auth(self):
        client = self._client()
        response = client.post("/dashboard/deploy/grafana", json={"viewModel": _VIEW_MODEL})
        self.assertEqual(response.status_code, 401)

    def test_deploy_grafana_rejects_empty(self):
        client = self._client()
        response = client.post("/dashboard/deploy/grafana", json={}, headers=self._auth)
        self.assertEqual(response.status_code, 400)

    def test_deploy_grafana_returns_url(self):
        client = self._client()
        result = {
            "url": "https://host/grafana/d/abc123def456",
            "uid": "abc123def456",
            "live": ["by_region"],
            "inline": [],
        }
        with patch("general_chat.server.app.deploy_view_model", return_value=result):
            response = client.post(
                "/dashboard/deploy/grafana",
                json={"viewModel": _VIEW_MODEL},
                headers=self._auth,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)

    def test_deploy_grafana_maps_deploy_error_to_503(self):
        from general_chat.server.grafana_client import GrafanaDeployError

        client = self._client()
        with patch(
            "general_chat.server.app.deploy_view_model",
            side_effect=GrafanaDeployError("Grafana unreachable"),
        ):
            response = client.post(
                "/dashboard/deploy/grafana",
                json={"viewModel": _VIEW_MODEL},
                headers=self._auth,
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("unreachable", response.json()["detail"])

    def _seed_live(self, client: TestClient, **overrides) -> LiveDashboardRecord:
        record = _live_record(**overrides)
        client.app.state.live_dashboard_store.save(record)
        return record

    def test_export_grafana_with_dashboard_id_uses_live_sql(self):
        client = self._client()
        record = self._seed_live(client)
        response = client.post(
            "/dashboard/export/grafana", json={"dashboardId": record.id}, headers=self._auth
        )
        self.assertEqual(response.status_code, 200, response.text)
        model = response.json()
        sqls = [t["rawSql"] for p in model["panels"] for t in p.get("targets", []) if "rawSql" in t]
        self.assertTrue(any("AS q LIMIT 500" in sql for sql in sqls))
        self.assertEqual(model["refresh"], "30s")

    def test_export_grafana_foreign_dashboard_is_404(self):
        client = self._client()
        record = self._seed_live(client, owner="someone-else@example.com")
        response = client.post(
            "/dashboard/export/grafana", json={"dashboardId": record.id}, headers=self._auth
        )
        self.assertEqual(response.status_code, 404)

    def test_export_grafana_static_path_unchanged(self):
        client = self._client()
        response = client.post(
            "/dashboard/export/grafana", json={"viewModel": _VIEW_MODEL}, headers=self._auth
        )
        self.assertEqual(response.status_code, 200)
        targets = [t for p in response.json()["panels"] for t in p.get("targets", [])]
        self.assertTrue(all(t.get("scenarioId") == "csv_content" for t in targets))
        self.assertEqual([i["name"] for i in response.json()["__inputs"]], ["DS_TESTDATA"])

    def test_deploy_grafana_with_dashboard_id_uses_live_deploy(self):
        client = self._client()
        record = self._seed_live(client)
        result = {
            "url": "https://host/grafana/d/abcdef123456",
            "uid": record.id,
            "live": ["by_region"],
            "inline": [],
        }
        with patch("general_chat.server.app.deploy_live_dashboard", return_value=result) as deploy:
            response = client.post(
                "/dashboard/deploy/grafana", json={"dashboardId": record.id}, headers=self._auth
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), result)
        self.assertEqual(deploy.call_args.args[0].id, record.id)

    def test_unknown_dashboard_id_is_404(self):
        client = self._client()
        self.assertEqual(client.get("/d/abcdef012345").status_code, 404)

    def test_non_hex_id_is_404(self):
        client = self._client()
        self.assertEqual(client.get("/d/not-a-valid-id").status_code, 404)


if __name__ == "__main__":
    unittest.main()
