"""Dashboard spec store tests for Dashboard Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pytest

DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "examples" / "dashboard-chat" / "src"
if str(DASHBOARD_SRC) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_SRC))


pytestmark = pytest.mark.integration


def _spec(**overrides) -> dict:
    spec = {
        "title": "Test Dashboard",
        "panels": [
            {
                "id": "kpi-1",
                "type": "kpi",
                "title": "Total",
                "width": "third",
                "sql": "SELECT 1",
            },
            {
                "id": "chart-1",
                "type": "bar",
                "title": "By category",
                "width": "half",
                "sql": "SELECT 'a' AS label, 1 AS value",
            },
        ],
    }
    spec.update(overrides)
    return spec


class TestValidateSpec(unittest.TestCase):
    def test_valid_spec(self):
        from dashboard_chat.dashboards import validate_spec

        self.assertEqual(validate_spec(_spec()), [])

    def test_missing_title(self):
        from dashboard_chat.dashboards import validate_spec

        errors = validate_spec(_spec(title=""))
        self.assertTrue(any("title" in error for error in errors))

    def test_empty_panels(self):
        from dashboard_chat.dashboards import validate_spec

        self.assertTrue(validate_spec(_spec(panels=[])))

    def test_duplicate_panel_ids(self):
        from dashboard_chat.dashboards import validate_spec

        spec = _spec()
        spec["panels"][1]["id"] = "kpi-1"
        errors = validate_spec(spec)
        self.assertTrue(any("duplicate" in error for error in errors))

    def test_unknown_type_and_width(self):
        from dashboard_chat.dashboards import validate_spec

        spec = _spec()
        spec["panels"][0]["type"] = "gauge"
        spec["panels"][1]["width"] = "quarter"
        errors = validate_spec(spec)
        self.assertEqual(len(errors), 2)

    def test_missing_sql(self):
        from dashboard_chat.dashboards import validate_spec

        spec = _spec()
        spec["panels"][0]["sql"] = "   "
        self.assertTrue(validate_spec(spec))


class TestNormalizeSpec(unittest.TestCase):
    def test_y_string_coerced_to_list(self):
        from dashboard_chat.dashboards import normalize_spec

        spec = _spec()
        spec["panels"][1]["y"] = "value"
        normalized = normalize_spec(spec)
        self.assertEqual(normalized["panels"][1]["y"], ["value"])

    def test_y_list_kept(self):
        from dashboard_chat.dashboards import normalize_spec

        spec = _spec()
        spec["panels"][1]["y"] = ["a", "b"]
        self.assertEqual(normalize_spec(spec)["panels"][1]["y"], ["a", "b"])

    def test_unknown_format_dropped(self):
        from dashboard_chat.dashboards import normalize_spec

        spec = _spec()
        spec["panels"][0]["format"] = "0.0"
        spec["panels"][1]["format"] = "currency"
        normalized = normalize_spec(spec)
        self.assertNotIn("format", normalized["panels"][0])
        self.assertEqual(normalized["panels"][1]["format"], "currency")

    def test_missing_width_defaulted(self):
        from dashboard_chat.dashboards import normalize_spec

        spec = _spec()
        del spec["panels"][0]["width"]
        self.assertEqual(normalize_spec(spec)["panels"][0]["width"], "half")

    def test_save_persists_normalized_form(self):
        import tempfile as _tempfile
        from pathlib import Path as _Path

        from dashboard_chat.dashboards import build_dashboard_store

        with _tempfile.TemporaryDirectory() as tmp:
            store = build_dashboard_store(_Path(tmp))
            spec = _spec()
            spec["panels"][1]["y"] = "value"
            spec["panels"][1]["format"] = "0.0"
            stored = store.save("alice", spec)
            self.assertEqual(stored["panels"][1]["y"], ["value"])
            self.assertNotIn("format", stored["panels"][1])
            self.assertEqual(store.get("alice")["panels"][1]["y"], ["value"])


class TestDashboardStore(unittest.TestCase):
    def setUp(self):
        from dashboard_chat.dashboards import build_dashboard_store

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = build_dashboard_store(Path(self._tmp.name))

    def test_get_before_save(self):
        self.assertIsNone(self.store.get("alice"))

    def test_save_stamps_version_and_timestamp(self):
        first = self.store.save("alice", _spec())
        self.assertEqual(first["version"], 1)
        self.assertIn("updatedAt", first)
        second = self.store.save("alice", _spec(title="Renamed"))
        self.assertEqual(second["version"], 2)
        self.assertEqual(self.store.get("alice")["title"], "Renamed")

    def test_invalid_spec_raises(self):
        with self.assertRaises(ValueError):
            self.store.save("alice", {"title": "x", "panels": []})

    def test_per_user_isolation(self):
        self.store.save("alice", _spec())
        self.assertIsNone(self.store.get("bob"))

    def test_invalid_username_rejected(self):
        with self.assertRaises(ValueError):
            self.store.get("../../etc/passwd")

    def test_delete(self):
        self.store.save("alice", _spec())
        self.store.delete("alice")
        self.assertIsNone(self.store.get("alice"))
        self.store.delete("alice")  # idempotent


if __name__ == "__main__":
    unittest.main()
