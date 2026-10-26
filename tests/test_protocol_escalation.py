"""Tests for the confidence marker protocol."""

import pytest

from openbench.intelligence.protocol import (
    CONFIDENCE_PROTOCOL_PROMPT,
    DEFAULT_CONFIDENCE_THRESHOLD,
    extract_confidence,
)


class TestExtractConfidence:
    def test_trailing_marker_stripped_and_parsed(self):
        text, confidence = extract_confidence("Jawaban lengkap.\n\n[[CONFIDENCE=0.8]]")
        assert text == "Jawaban lengkap."
        assert confidence == 0.8

    def test_marker_with_trailing_whitespace(self):
        text, confidence = extract_confidence("Jawaban.\n[[CONFIDENCE=0.35]]   \n")
        assert text == "Jawaban."
        assert confidence == 0.35

    def test_integer_bounds(self):
        assert extract_confidence("A\n[[CONFIDENCE=0]]") == ("A", 0.0)
        assert extract_confidence("A\n[[CONFIDENCE=1]]") == ("A", 1.0)
        assert extract_confidence("A\n[[CONFIDENCE=1.0]]") == ("A", 1.0)

    def test_missing_marker_means_confident(self):
        text, confidence = extract_confidence("Jawaban tanpa marker.")
        assert text == "Jawaban tanpa marker."
        assert confidence is None

    def test_empty_text(self):
        assert extract_confidence("") == ("", None)

    def test_mid_text_marker_left_alone(self):
        raw = "Sebelum [[CONFIDENCE=0.2]] sesudah."
        text, confidence = extract_confidence(raw)
        assert text == raw
        assert confidence is None

    def test_multiline_answer_preserved(self):
        raw = "Baris satu.\n- poin a\n- poin b\n\n[[CONFIDENCE=0.9]]"
        text, confidence = extract_confidence(raw)
        assert text == "Baris satu.\n- poin a\n- poin b"
        assert confidence == 0.9

    def test_out_of_range_value_stripped_but_ignored(self):
        text, confidence = extract_confidence("A\n[[CONFIDENCE=1.5]]")
        assert text == "A"
        assert confidence is None

    @pytest.mark.parametrize(
        "raw",
        [
            "A [[CONFIDENCE=abc]]",
            "A [[CONFIDENCE=]]",
            "A [[confidence=0.5]]",
            "A [[CONFIDENCE=0.5]",
            "A [[CONFIDENCE=2]]",
            "A [[CONFIDENCE=-0.5]]",
        ],
    )
    def test_malformed_markers_ignored(self, raw):
        text, confidence = extract_confidence(raw)
        assert text == raw
        assert confidence is None

    def test_only_last_marker_stripped(self):
        raw = "A\n[[CONFIDENCE=0.9]]\nB\n[[CONFIDENCE=0.4]]"
        text, confidence = extract_confidence(raw)
        assert confidence == 0.4
        assert text == "A\n[[CONFIDENCE=0.9]]\nB"


class TestProtocolConstants:
    def test_default_threshold(self):
        assert DEFAULT_CONFIDENCE_THRESHOLD == 0.5

    def test_prompt_mentions_marker_form(self):
        assert "[[CONFIDENCE=0.8]]" in CONFIDENCE_PROTOCOL_PROMPT
        assert "final line" in CONFIDENCE_PROTOCOL_PROMPT

    def test_prompt_example_round_trips(self):
        """The exact form shown in the prompt must parse."""
        text, confidence = extract_confidence("Answer.\n\n[[CONFIDENCE=0.8]]")
        assert text == "Answer."
        assert confidence == 0.8
