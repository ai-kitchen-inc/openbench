"""Tests for the agent profile store (JSON + Postgres backends)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.agent_store import (  # noqa: E402
    AgentProfileRecord,
    DuplicateAgentProfileError,
    JsonAgentProfileStore,
    PostgresAgentProfileStore,
    UnknownAgentProfileError,
    slugify_agent_name,
    validate_agent_id,
)

pytestmark = pytest.mark.integration


def _record(name: str = "Analis Keuangan", **overrides) -> AgentProfileRecord:
    values = {
        "id": slugify_agent_name(name),
        "name": name,
        "description": "Laporan keuangan, anggaran, pajak.",
    }
    values.update(overrides)
    return AgentProfileRecord(**values)


class TestRecord(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify_agent_name("Analis Keuangan & Pajak"), "analis-keuangan-pajak")

    def test_validate_agent_id_rejects_bad(self):
        with self.assertRaises(ValueError):
            validate_agent_id("Not A Slug!")

    def test_from_dict_defaults_every_missing_key(self):
        record = AgentProfileRecord.from_dict({"id": "a", "name": "A"})
        self.assertTrue(record.enabled)
        self.assertEqual(record.persona, {})
        self.assertEqual(record.model, "")
        self.assertIsNone(record.temperature)
        self.assertEqual(record.skills, [])
        self.assertEqual(record.custom_skill_ids, [])
        self.assertTrue(record.use_sources)
        self.assertEqual(record.escalation_agent_id, "")
        self.assertEqual(record.confidence_threshold, 0.5)
        self.assertTrue(record.created_at)

    def test_round_trip(self):
        record = _record(
            persona={"soul": "Saya analis."},
            model="gemini-2.5-pro",
            temperature=0.1,
            skills=["export-excel"],
            custom_skill_ids=["ldi-parser"],
            use_sources=False,
            escalation_agent_id="konsultan-senior",
            confidence_threshold=0.7,
        )
        restored = AgentProfileRecord.from_dict(record.to_dict())
        self.assertEqual(restored.to_dict(), record.to_dict())

    def test_threshold_clamped(self):
        self.assertEqual(
            AgentProfileRecord.from_dict(
                {"id": "a", "name": "A", "confidenceThreshold": 3}
            ).confidence_threshold,
            1.0,
        )
        self.assertEqual(
            AgentProfileRecord.from_dict(
                {"id": "a", "name": "A", "confidenceThreshold": "junk"}
            ).confidence_threshold,
            0.5,
        )

    def test_apply_changes_partial(self):
        record = _record()
        before_created = record.created_at
        record.apply_changes(
            {
                "description": "  Baru  ",
                "enabled": False,
                "model": "gemini-2.5-flash",
                "skills": ["export-excel", " ", 42],
                "escalation_agent_id": "Konsultan-Senior",
                "confidence_threshold": -1,
            }
        )
        self.assertEqual(record.description, "Baru")
        self.assertFalse(record.enabled)
        self.assertEqual(record.model, "gemini-2.5-flash")
        self.assertEqual(record.skills, ["export-excel", "42"])
        self.assertEqual(record.escalation_agent_id, "konsultan-senior")
        self.assertEqual(record.confidence_threshold, 0.0)
        self.assertEqual(record.created_at, before_created)
        self.assertEqual(record.name, "Analis Keuangan")  # untouched

    def test_apply_changes_blank_name_ignored(self):
        record = _record()
        record.apply_changes({"name": "   "})
        self.assertEqual(record.name, "Analis Keuangan")


class TestJsonAgentProfileStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonAgentProfileStore(tmp.name)

    def test_crud_round_trip(self):
        record = self.store.add(_record())
        self.assertEqual(record.id, "analis-keuangan")
        loaded = self.store.get("analis-keuangan")
        self.assertEqual(loaded.name, "Analis Keuangan")
        updated = self.store.update("analis-keuangan", {"description": "Departemen keuangan"})
        self.assertEqual(updated.description, "Departemen keuangan")
        self.assertEqual([a.id for a in self.store.list()], ["analis-keuangan"])
        self.assertTrue(self.store.remove("analis-keuangan"))
        self.assertFalse(self.store.remove("analis-keuangan"))
        self.assertIsNone(self.store.get("analis-keuangan"))

    def test_duplicate_rejected(self):
        self.store.add(_record("HR Bot"))
        with self.assertRaises(DuplicateAgentProfileError):
            self.store.add(_record("hr bot"))

    def test_update_unknown_raises(self):
        with self.assertRaises(UnknownAgentProfileError):
            self.store.update("missing", {"description": "x"})

    def test_persisted_shape_survives_reload(self):
        self.store.add(_record(skills=["export-excel"], persona={"soul": "S"}))
        # A brand-new store instance reads the same file.
        reloaded = JsonAgentProfileStore(self.store._path.parents[1])
        record = reloaded.get("analis-keuangan")
        self.assertEqual(record.skills, ["export-excel"])
        self.assertEqual(record.persona, {"soul": "S"})


class TestPostgresAgentProfileStoreStructure(unittest.TestCase):
    def test_sql_shape_and_interface(self):
        executed: list[str] = []

        class _Cursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Conn:
            def cursor(self):
                return _Cursor()

            def commit(self):
                pass

        PostgresAgentProfileStore(conn=_Conn())
        joined = "\n".join(executed)
        self.assertIn("openbench_agent_profiles", joined)
        for column in ("id TEXT PRIMARY KEY", "enabled BOOLEAN", "config TEXT"):
            self.assertIn(column, joined)
        for method in ("list", "get", "add", "update", "remove"):
            self.assertTrue(callable(getattr(PostgresAgentProfileStore, method, None)))

    def test_record_from_row_parses_config_json(self):
        record = PostgresAgentProfileStore._record_from_row((json.dumps(_record().to_dict()),))
        self.assertEqual(record.id, "analis-keuangan")
        self.assertEqual(record.name, "Analis Keuangan")

    def test_record_from_row_tolerates_junk(self):
        record = PostgresAgentProfileStore._record_from_row(("{not json",))
        self.assertEqual(record.id, "")


if __name__ == "__main__":
    unittest.main()
