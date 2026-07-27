"""Tests for the per-turn source-context budget and attachment dedupe.

Without a budget, every ready source's full text is injected into the
current user message, which the history trimmer explicitly exempts — so a
session with enough sources fails with a provider 400 instead of giving a
degraded answer.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_EXAMPLE_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(_EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_SRC))

from general_chat.server.handler import (  # noqa: E402
    _SOURCE_BUDGET_NOTE_ID,
    _apply_source_context_budget,
    _fair_shares,
    _merge_attachments,
)

from openbench.chat.session import Attachment  # noqa: E402


def _attachment(name: str, text: str, *, att_id: str = "", size: int = 0) -> Attachment:
    return Attachment(
        id=att_id or name,
        type="file",
        name=name,
        url="",
        mime_type="text/plain",
        size_bytes=size,
        extracted_text=text,
    )


class TestFairShares(unittest.TestCase):
    def test_equal_sources_get_equal_shares(self):
        self.assertEqual(_fair_shares([1000, 1000], 400), [200, 200])

    def test_small_source_is_never_truncated(self):
        # 10 chars fits easily; the rest of the budget goes to the big one.
        shares = _fair_shares([10, 100_000], 1_000)
        self.assertEqual(shares[0], 10)
        self.assertEqual(shares[1], 990)

    def test_everything_fits(self):
        self.assertEqual(_fair_shares([10, 20], 1_000), [10, 20])

    def test_empty_sources_get_nothing(self):
        self.assertEqual(_fair_shares([0, 50], 100), [0, 50])


class TestSourceContextBudget(unittest.TestCase):
    def test_under_budget_is_untouched(self):
        attachments = [_attachment("a.txt", "x" * 10), _attachment("b.txt", "y" * 10)]
        result = _apply_source_context_budget(attachments)
        self.assertEqual(result, attachments)

    @mock.patch.dict(os.environ, {"GENERAL_CHAT_SOURCE_CONTEXT_CHAR_BUDGET": "4000"})
    def test_over_budget_truncates_and_annotates(self):
        attachments = [_attachment("big.txt", "x" * 10_000), _attachment("also.txt", "y" * 10_000)]
        result = _apply_source_context_budget(attachments)

        # Original two, plus the summary note.
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1].id, _SOURCE_BUDGET_NOTE_ID)
        for attachment in result[:2]:
            self.assertIn("[TRUNCATED:", attachment.extracted_text)
            self.assertIn(attachment.name, attachment.extracted_text)
        body_chars = sum(len(a.extracted_text) for a in result[:2])
        # Bounded by the budget plus the per-source truncation markers.
        self.assertLess(body_chars, 4000 + 500)

    @mock.patch.dict(os.environ, {"GENERAL_CHAT_SOURCE_CONTEXT_CHAR_BUDGET": "4000"})
    def test_summary_note_lists_every_trimmed_source(self):
        attachments = [_attachment("big.txt", "x" * 10_000), _attachment("also.txt", "y" * 10_000)]
        note = _apply_source_context_budget(attachments)[-1]
        self.assertIn("big.txt", note.extracted_text)
        self.assertIn("also.txt", note.extracted_text)

    @mock.patch.dict(
        os.environ,
        {
            "GENERAL_CHAT_SOURCE_CONTEXT_CHAR_BUDGET": "5000",
            "GENERAL_CHAT_SOURCE_CONTEXT_MIN_CHARS": "2000",
        },
    )
    def test_keeps_recent_sources_whole_when_shares_are_too_small(self):
        # 10 sources sharing 5000 chars would give 500 each — below the
        # minimum, so the most recent whole sources are kept instead.
        attachments = [_attachment(f"s{i}.txt", "x" * 2_400) for i in range(10)]
        result = _apply_source_context_budget(attachments)
        bodies = result[:10]
        whole = [
            a
            for a in bodies
            if "[TRUNCATED:" not in a.extracted_text and "[OMITTED:" not in a.extracted_text
        ]
        omitted = [a for a in bodies if "[OMITTED:" in a.extracted_text]
        self.assertEqual([a.name for a in whole], ["s8.txt", "s9.txt"])
        self.assertEqual(len(omitted), 8)

    @mock.patch.dict(os.environ, {"GENERAL_CHAT_SOURCE_CONTEXT_CHAR_BUDGET": "0"})
    def test_zero_budget_disables_the_cap(self):
        attachments = [_attachment("big.txt", "x" * 10_000)]
        self.assertEqual(_apply_source_context_budget(attachments), attachments)

    def test_routing_fields_survive_truncation(self):
        attachment = Attachment(
            id="rec-1",
            type="file",
            name="sheet.xlsx",
            url="/uploads/x/sheet.xlsx",
            mime_type="application/vnd.ms-excel",
            size_bytes=99,
            path="/general-chat/uploads/x/sheet.xlsx",
            extracted_text="z" * 10_000,
        )
        with mock.patch.dict(os.environ, {"GENERAL_CHAT_SOURCE_CONTEXT_CHAR_BUDGET": "100"}):
            trimmed = _apply_source_context_budget([attachment])[0]
        self.assertEqual(trimmed.path, attachment.path)
        self.assertEqual(trimmed.url, attachment.url)
        self.assertEqual(trimmed.size_bytes, attachment.size_bytes)


class TestMergeAttachments(unittest.TestCase):
    def test_composer_duplicate_is_dropped_by_id(self):
        draft = [_attachment("report.pdf", "composer copy", att_id="rec-1")]
        source = [_attachment("report.pdf", "server copy with routing", att_id="rec-1")]
        merged = _merge_attachments(draft, source)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].extracted_text, "server copy with routing")

    def test_duplicate_dropped_by_name_and_size_for_older_clients(self):
        draft = [_attachment("report.pdf", "composer copy", att_id="local-1", size=42)]
        source = [_attachment("report.pdf", "server copy", att_id="rec-1", size=42)]
        merged = _merge_attachments(draft, source)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].extracted_text, "server copy")

    def test_unrelated_draft_attachment_is_kept(self):
        draft = [_attachment("pasted.png", "image", att_id="local-9", size=7)]
        source = [_attachment("report.pdf", "server copy", att_id="rec-1", size=42)]
        merged = _merge_attachments(draft, source)
        self.assertEqual([a.name for a in merged], ["pasted.png", "report.pdf"])


if __name__ == "__main__":
    unittest.main()
