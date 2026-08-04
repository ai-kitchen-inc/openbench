"""Per-turn source context: cards, retrieved passages, and scope.

The behavioural contract these lock down:

* ``full`` mode must reproduce the old prompt exactly — it is the
  rollback path.
* card mode must never carry a document's full text.
* the turn scope must cover exactly the indexed sources, including
  admin-curated global ones, and nothing else.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

EXAMPLE_SRC = Path(__file__).resolve().parent.parent / "examples" / "general-chat" / "src"
if str(EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_SRC))

try:
    from general_chat.server import source_context
    from general_chat.server.source_context import (
        MODE_AUTO,
        MODE_CARDS,
        MODE_FULL,
        SourceScope,
        build_source_attachments,
        build_source_card,
        current_source_scope,
        is_indexed,
        set_source_scope,
    )
    from general_chat.sources import SourceRecord

    HAS_GENERAL_CHAT = True
except ImportError:  # pragma: no cover - example deps not installed
    HAS_GENERAL_CHAT = False


LONG_TEXT = "Pendapatan naik dua belas persen dibanding tahun lalu. " * 200


def _record(
    source_id="source-1",
    *,
    name="laporan.pdf",
    kind="document",
    indexed=True,
    owner="alice@example.com",
    session_id="s1",
    metadata=None,
    text=LONG_TEXT,
):
    record = SourceRecord.create(
        session_id=session_id,
        name=name,
        kind=kind,
        mime_type="application/pdf",
        size_bytes=2_400_000,
        text=text,
        owner=owner,
    )
    record.id = source_id
    extra = dict(metadata or {})
    if indexed:
        extra.setdefault("indexStatus", "ready")
        extra.setdefault("chunkCount", 128)
        extra.setdefault("summary", "Laporan kinerja kuartal ketiga.")
        extra.setdefault(
            "outline",
            [
                {"heading": "Ringkasan Eksekutif", "chunk_index": 0},
                {"heading": "Pendapatan", "chunk_index": 12},
            ],
        )
    record.metadata = extra
    return record


def _workbook_record(source_id: str, *, sheets: int = 25):
    """A spreadsheet source shaped like the real RAB uploads.

    Many sheets, each with a wide column list — the shape that blew the
    card budget in production.
    """
    tables = []
    for sheet in range(sheets):
        columns = "\n".join(
            f"  - Kolom {col} untuk kebutuhan alat kesehatan str (30 distinct) [12 null]"
            for col in range(14)
        )
        tables.append(
            {
                "table": f"sheet_{sheet}",
                "displayName": f"Sheet {sheet}",
                "rowCount": 120,
                "columnCount": 14,
                "schemaCard": f'Table "sheet_{sheet}"  120 rows x 14 cols\n{columns}',
            }
        )
    return _record(
        source_id,
        name=f"RAB ALKES {source_id}.xlsx",
        kind="spreadsheet",
        metadata={
            "localFilePath": f"/general-chat/uploads/file-{source_id}/rab.xlsx",
            "tables": tables,
        },
    )


class _FakeIndex:
    def __init__(self, items=None, fail=False):
        self.items = items if items is not None else []
        self.fail = fail
        self.last_query = None

    def search(self, query):
        self.last_query = query
        if self.fail:
            raise RuntimeError("index offline")

        class _Result:
            def __init__(self, items):
                self.items = items
                self.scores = [1.0] * len(items)
                self.total = len(items)

        return _Result(self.items)


def _legacy_builder(records):
    """Stand-in for the existing full-text attachment builder."""
    from openbench.chat.session import Attachment

    return [
        Attachment(
            id=record.id,
            type="file",
            name=record.name,
            url="",
            mime_type="text/markdown",
            extracted_text=f"Source name: {record.name}\n\n{record.text}",
        )
        for record in records
    ]


@unittest.skipUnless(HAS_GENERAL_CHAT, "general-chat example is not importable")
class SourceContextTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in (
                "GENERAL_CHAT_SOURCE_CONTEXT_MODE",
                "GENERAL_CHAT_RETRIEVAL_TOP_K",
                "GENERAL_CHAT_SOURCE_CARD_BUDGET",
            )
        }
        set_source_scope(None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        set_source_scope(None)

    def _set_mode(self, mode):
        os.environ["GENERAL_CHAT_SOURCE_CONTEXT_MODE"] = mode


class TestMode(SourceContextTestCase):
    def test_default_mode_is_full(self):
        os.environ.pop("GENERAL_CHAT_SOURCE_CONTEXT_MODE", None)
        self.assertEqual(source_context.source_context_mode(), MODE_FULL)

    def test_unknown_mode_falls_back_to_full(self):
        self._set_mode("nonsense")
        self.assertEqual(source_context.source_context_mode(), MODE_FULL)

    def test_known_modes_are_honoured(self):
        for mode in (MODE_FULL, MODE_AUTO, MODE_CARDS):
            with self.subTest(mode=mode):
                self._set_mode(mode)
                self.assertEqual(source_context.source_context_mode(), mode)


class TestFullModeIsUnchanged(SourceContextTestCase):
    """Rollback contract: full mode must be byte-identical to the old path."""

    def test_full_mode_delegates_entirely_to_the_legacy_builder(self):
        self._set_mode(MODE_FULL)
        records = [_record(), _record("source-2", name="kedua.pdf")]
        built = build_source_attachments(
            records, "berapa pendapatan?", index=_FakeIndex(), legacy_builder=_legacy_builder
        )
        expected = _legacy_builder(records)
        self.assertEqual([a.extracted_text for a in built], [a.extracted_text for a in expected])

    def test_full_mode_publishes_no_scope(self):
        self._set_mode(MODE_FULL)
        build_source_attachments(
            [_record()], "berapa?", index=_FakeIndex(), legacy_builder=_legacy_builder
        )
        self.assertIsNone(current_source_scope())

    def test_full_mode_never_calls_the_index(self):
        self._set_mode(MODE_FULL)
        index = _FakeIndex()
        build_source_attachments(
            [_record()], "berapa pendapatan?", index=index, legacy_builder=_legacy_builder
        )
        self.assertIsNone(index.last_query)


class TestCard(SourceContextTestCase):
    def test_card_names_the_source_and_its_id(self):
        card = build_source_card(_record())
        self.assertIn("laporan.pdf", card.extracted_text)
        self.assertIn("source-1", card.extracted_text)

    def test_card_omits_the_document_text(self):
        card = build_source_card(_record())
        self.assertNotIn("Pendapatan naik dua belas persen", card.extracted_text)

    def test_card_carries_outline_and_summary(self):
        card = build_source_card(_record())
        self.assertIn("Ringkasan Eksekutif", card.extracted_text)
        self.assertIn("Laporan kinerja kuartal ketiga", card.extracted_text)

    def test_card_tells_the_model_how_to_read_more(self):
        card = build_source_card(_record())
        self.assertIn("search_sources", card.extracted_text)

    def test_card_is_compact(self):
        self.assertLess(len(build_source_card(_record()).extracted_text), 1200)

    def test_card_includes_the_framing_label(self):
        card = build_source_card(_record(), label="Grounding wajib.")
        self.assertIn("Grounding wajib.", card.extracted_text)

    def test_spreadsheet_card_carries_the_schema_and_sql_routing(self):
        record = _record(
            "source-x",
            name="penjualan.xlsx",
            kind="spreadsheet",
            metadata={
                "localFilePath": "/general-chat/uploads/file-abc/penjualan.xlsx",
                "tables": [
                    {
                        "table": "penjualan_2024",
                        "rowCount": 40102,
                        "schemaCard": 'Table "penjualan_2024"  40,102 rows x 3 cols\n  - cabang',
                    }
                ],
            },
        )
        card = build_source_card(record).extracted_text
        self.assertIn("penjualan_2024", card)
        self.assertIn("query_source_table", card)

    def test_spreadsheet_card_preserves_dashboard_routing(self):
        record = _record(
            "source-x",
            kind="spreadsheet",
            metadata={"localFilePath": "/general-chat/uploads/file-abc/penjualan.xlsx"},
        )
        card = build_source_card(record).extracted_text
        # The per-source path stays on the card; the instructions that go
        # with it are emitted once per turn by the routing note.
        self.assertIn("Dashboard source path:", card)
        note = source_context.build_routing_note([record])
        self.assertIsNotNone(note)
        self.assertIn("aggregate_data.extract_metadata", note.extracted_text)
        self.assertIn("dashboard_generator.search_dashboards", note.extracted_text)

    def test_image_card_preserves_image_tool_paths(self):
        record = _record(
            "source-img",
            name="foto.jpg",
            kind="image",
            metadata={
                "imageSearchPath": "/general-chat/uploads/file-i/foto.jpg",
                "samSegmentationPath": "/general-chat/uploads/file-i/foto.jpg",
            },
        )
        card = build_source_card(record)
        self.assertEqual(card.type, "image")
        self.assertIn("Image search path:", card.extracted_text)
        self.assertIn("SAM 3 concept counting path:", card.extracted_text)

    def test_template_card_preserves_template_routing(self):
        record = _record(
            "source-t",
            kind="dashboard_template",
            metadata={"dashboardTemplatePath": "/general-chat/uploads/file-t/tpl.json"},
        )
        card = build_source_card(record).extracted_text
        self.assertIn("Dashboard template path:", card)
        note = source_context.build_routing_note([record])
        self.assertIsNotNone(note)
        self.assertIn("generate_dashboard(template_path=", note.extracted_text)


class TestCardMode(SourceContextTestCase):
    def setUp(self):
        super().setUp()
        self._set_mode(MODE_AUTO)

    def test_indexed_sources_become_cards(self):
        built = build_source_attachments(
            [_record()], "berapa pendapatan?", index=_FakeIndex(), legacy_builder=_legacy_builder
        )
        self.assertTrue(built)
        joined = "\n".join(a.extracted_text or "" for a in built)
        self.assertNotIn("Pendapatan naik dua belas persen", joined)

    def test_scope_covers_exactly_the_indexed_sources(self):
        build_source_attachments(
            [_record(), _record("source-2")],
            "berapa pendapatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        scope = current_source_scope()
        self.assertEqual(set(scope.source_ids), {"source-1", "source-2"})
        self.assertEqual(scope.owner, "alice@example.com")

    def test_scope_includes_admin_global_sources(self):
        # Global sources live under a different owner and session; a
        # session-only filter would silently drop them.
        build_source_attachments(
            [
                _record("source-mine"),
                _record("source-global", owner="shared", session_id="global-sources"),
            ],
            "berapa pendapatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        self.assertIn("source-global", current_source_scope().source_ids)

    def test_retrieval_filter_spans_mixed_owner_sources(self):
        # Production ordering: admin-curated globals (owner "shared") come
        # first, then the session's own sources. The retrieval filter must
        # carry every scoped id and no owner — an owner AND-filter took the
        # first record's owner and silently dropped the user's own sources.
        index = _FakeIndex(
            items=[{"content": "hit", "metadata": {"name": "laporan.pdf", "chunk_index": 0}}]
        )
        build_source_attachments(
            [
                _record("source-global", owner="shared", session_id="global-sources"),
                _record("source-mine"),
            ],
            "berapa pendapatan?",
            index=index,
            legacy_builder=_legacy_builder,
        )
        filters = index.last_query.filters
        self.assertEqual(set(filters["source_ids"]), {"source-global", "source-mine"})
        self.assertNotIn("owner", filters)

    def test_unindexed_sources_fall_back_to_full_text_in_auto_mode(self):
        built = build_source_attachments(
            [_record("source-old", indexed=False)],
            "berapa pendapatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        joined = "\n".join(a.extracted_text or "" for a in built)
        self.assertIn("Pendapatan naik dua belas persen", joined)

    def test_mixed_indexed_and_legacy_sources(self):
        built = build_source_attachments(
            [_record("source-new"), _record("source-old", indexed=False)],
            "berapa pendapatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        self.assertEqual(current_source_scope().source_ids, ("source-new",))
        self.assertGreaterEqual(len(built), 2)

    def test_cards_mode_suppresses_the_full_text_fallback(self):
        self._set_mode(MODE_CARDS)
        built = build_source_attachments(
            [_record("source-old", indexed=False)],
            "berapa pendapatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        joined = "\n".join(a.extracted_text or "" for a in built)
        self.assertNotIn("Pendapatan naik dua belas persen", joined)

    def test_twenty_sources_stay_within_the_card_budget(self):
        records = [_record(f"source-{index}") for index in range(20)]
        built = build_source_attachments(
            records, "berapa pendapatan?", index=_FakeIndex(), legacy_builder=_legacy_builder
        )
        total = sum(len(a.extracted_text or "") for a in built)
        self.assertLess(total, source_context.card_budget() + 4000)

    def test_many_multi_sheet_workbooks_keep_every_source(self):
        """Reproduces the production regression.

        34 spreadsheets, each a workbook with many sheets. Rendering every
        sheet's schema made the card set 243k chars, and the old trimmer
        responded by deleting whole cards — 32 of 34 sources vanished from
        the prompt entirely.
        """
        records = [_workbook_record(f"source-wb{index}", sheets=25) for index in range(34)]
        built = build_source_attachments(
            records,
            "berapa total harga alat kesehatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        cards = [a for a in built if a.id.startswith(source_context.SOURCE_CARD_PREFIX)]
        self.assertEqual(len(cards), 34, "every source must still have a card")

        card_chars = sum(len(a.extracted_text or "") for a in cards)
        self.assertLessEqual(
            card_chars,
            source_context.card_budget(),
            f"cards were {card_chars:,} chars, over the {source_context.card_budget():,} budget",
        )

        # The equivalent full-text prompt for this session in production
        # was ~53k chars; the whole point is to be well under that.
        total = sum(len(a.extracted_text or "") for a in built)
        self.assertLess(total, 30_000, f"total context was {total:,} chars")

    def test_shared_routing_text_is_not_repeated_per_card(self):
        records = [_workbook_record(f"source-wb{index}", sheets=4) for index in range(10)]
        built = build_source_attachments(
            records, "berapa total?", index=_FakeIndex(), legacy_builder=_legacy_builder
        )
        joined = "\n".join(a.extracted_text or "" for a in built)
        # The dashboard instructions appear once, in the shared note.
        self.assertEqual(joined.count("aggregate_data.extract_metadata"), 1)
        notes = [a for a in built if a.id == source_context.ROUTING_NOTE_ID]
        self.assertEqual(len(notes), 1)
        # Per-source paths still ride on each card.
        for record in records:
            self.assertIn(record.metadata["localFilePath"], joined)

    def test_no_routing_note_without_tool_bearing_sources(self):
        built = build_source_attachments(
            [_record()],
            "berapa pendapatan?",
            index=_FakeIndex(),
            legacy_builder=_legacy_builder,
        )
        self.assertFalse([a for a in built if a.id == source_context.ROUTING_NOTE_ID])

    def test_every_source_id_appears_in_the_prompt(self):
        records = [_workbook_record(f"source-wb{index}", sheets=25) for index in range(34)]
        built = build_source_attachments(
            records, "berapa total?", index=_FakeIndex(), legacy_builder=_legacy_builder
        )
        joined = "\n".join(a.extracted_text or "" for a in built)
        for record in records:
            self.assertIn(record.id, joined)

    def test_unrendered_tables_are_still_named(self):
        record = _workbook_record("source-wb", sheets=25)
        card = build_source_card(record, max_tables=3, max_table_columns=10)
        text = card.extracted_text
        # Tables past the rendered few are named, not silently dropped.
        self.assertIn("more table(s)", text)
        self.assertIn("25 table(s) total", text)
        self.assertIn("query_source_table", text)
        # How to get the columns that aren't shown lives in the note.
        note = source_context.build_routing_note([record])
        self.assertIn("describe_source_table", note.extracted_text)

    def test_no_records_publishes_no_scope(self):
        self.assertEqual(
            build_source_attachments([], "hi", index=_FakeIndex(), legacy_builder=_legacy_builder),
            [],
        )
        self.assertIsNone(current_source_scope())


class TestRetrievedContext(SourceContextTestCase):
    def setUp(self):
        super().setUp()
        self._set_mode(MODE_AUTO)
        self.index = _FakeIndex(
            items=[
                {
                    "id": "source-1-chunk-12",
                    "content": "Pendapatan naik dua belas persen.",
                    "metadata": {
                        "source_id": "source-1",
                        "name": "laporan.pdf",
                        "chunk_index": 12,
                        "heading": "Pendapatan",
                    },
                }
            ]
        )

    def test_passages_are_injected_eagerly(self):
        built = build_source_attachments(
            [_record()],
            "berapa pendapatan tahun ini?",
            index=self.index,
            legacy_builder=_legacy_builder,
        )
        retrieved = [a for a in built if a.id == source_context.RETRIEVED_CONTEXT_ID]
        self.assertEqual(len(retrieved), 1)
        self.assertIn("Pendapatan naik dua belas persen", retrieved[0].extracted_text)

    def test_retrieved_block_cites_source_and_heading(self):
        built = build_source_attachments(
            [_record()],
            "berapa pendapatan tahun ini?",
            index=self.index,
            legacy_builder=_legacy_builder,
        )
        text = next(a for a in built if a.id == source_context.RETRIEVED_CONTEXT_ID).extracted_text
        self.assertIn("laporan.pdf", text)
        self.assertIn("Pendapatan", text)
        self.assertIn("chunk 12", text)

    def test_retrieval_is_scoped_to_this_turn(self):
        build_source_attachments(
            [_record()],
            "berapa pendapatan tahun ini?",
            index=self.index,
            legacy_builder=_legacy_builder,
        )
        self.assertEqual(self.index.last_query.filters["source_ids"], ["source-1"])

    def test_top_k_is_configurable(self):
        os.environ["GENERAL_CHAT_RETRIEVAL_TOP_K"] = "3"
        build_source_attachments(
            [_record()],
            "berapa pendapatan tahun ini?",
            index=self.index,
            legacy_builder=_legacy_builder,
        )
        self.assertEqual(self.index.last_query.limit, 3)

    def test_short_messages_skip_retrieval(self):
        build_source_attachments(
            [_record()], "ok", index=self.index, legacy_builder=_legacy_builder
        )
        self.assertIsNone(self.index.last_query)

    def test_no_hits_adds_no_attachment(self):
        built = build_source_attachments(
            [_record()],
            "pertanyaan tanpa jawaban",
            index=_FakeIndex(items=[]),
            legacy_builder=_legacy_builder,
        )
        self.assertFalse([a for a in built if a.id == source_context.RETRIEVED_CONTEXT_ID])

    def test_retrieval_failure_degrades_to_cards(self):
        built = build_source_attachments(
            [_record()],
            "berapa pendapatan tahun ini?",
            index=_FakeIndex(fail=True),
            legacy_builder=_legacy_builder,
        )
        self.assertTrue(built)
        self.assertFalse([a for a in built if a.id == source_context.RETRIEVED_CONTEXT_ID])

    def test_missing_index_degrades_to_cards(self):
        built = build_source_attachments(
            [_record()],
            "berapa pendapatan tahun ini?",
            index=None,
            legacy_builder=_legacy_builder,
        )
        self.assertTrue(built)
        self.assertFalse([a for a in built if a.id == source_context.RETRIEVED_CONTEXT_ID])


class TestIsIndexed(SourceContextTestCase):
    def test_ready_is_indexed(self):
        self.assertTrue(is_indexed(_record()))

    def test_failed_and_skipped_are_not_indexed(self):
        for status in ("failed", "skipped", None):
            with self.subTest(status=status):
                record = _record(indexed=False, metadata={"indexStatus": status})
                self.assertFalse(is_indexed(record))


class TestScopeContextVar(SourceContextTestCase):
    def test_scope_round_trips(self):
        scope = SourceScope(session_id="s1", owner="a@b.c", source_ids=("source-1",))
        set_source_scope(scope)
        self.assertEqual(current_source_scope(), scope)

    def test_scope_is_visible_in_a_copied_context(self):
        # ToolExecutor runs tools in worker threads via copy_context();
        # this is what makes one shared binding safe across requests.
        import contextvars

        set_source_scope(SourceScope(source_ids=("source-1",)))
        seen = contextvars.copy_context().run(current_source_scope)
        self.assertEqual(seen.source_ids, ("source-1",))


if __name__ == "__main__":
    unittest.main()
