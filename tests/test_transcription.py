"""Tests for swappable transcription + audio extraction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openbench.chat.files import FileContentExtractor, StoredFile
from openbench.core.abstractions import TranscriptionProvider


class _FakeTranscriber(TranscriptionProvider):
    """In-memory transcriber — proves the extractor depends on the abstraction."""

    def __init__(self):
        self.calls: list[tuple] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    def transcribe(self, audio, model: str = "", **params) -> str:
        self.calls.append((audio, params.get("mime_type")))
        return "hello transcript"


class TestAudioExtraction(unittest.TestCase):
    """Audio routes through the resolved TranscriptionProvider."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.audio = Path(self.tmp) / "note.mp3"
        self.audio.write_bytes(b"ID3fake-audio-bytes")
        self.stored = StoredFile(
            id="file-a",
            name="note.mp3",
            path=str(self.audio),
            mime_type="audio/mpeg",
            size_bytes=self.audio.stat().st_size,
            stored_at="2026-01-01T00:00:00+00:00",
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_audio_routed_to_transcriber(self):
        fake = _FakeTranscriber()
        # Patch the resolver — extractor must not import Gemini directly.
        with patch(
            "openbench.intelligence.transcription.get_transcriber", return_value=fake
        ):
            text = FileContentExtractor().extract(self.stored)
        self.assertEqual(text, "hello transcript")
        self.assertEqual(fake.calls[0][1], "audio/mpeg")

    def test_transcription_failure_degrades(self):
        class _Boom(TranscriptionProvider):
            @property
            def provider_name(self):
                return "boom"

            def transcribe(self, audio, model="", **params):
                raise RuntimeError("api down")

        with patch(
            "openbench.intelligence.transcription.get_transcriber", return_value=_Boom()
        ):
            text = FileContentExtractor().extract(self.stored)
        self.assertIn("transcription failed", text)

    def test_empty_transcript_reports_no_speech(self):
        class _Silent(TranscriptionProvider):
            @property
            def provider_name(self):
                return "silent"

            def transcribe(self, audio, model="", **params):
                return "   "

        with patch(
            "openbench.intelligence.transcription.get_transcriber", return_value=_Silent()
        ):
            text = FileContentExtractor().extract(self.stored)
        self.assertIn("no speech detected", text)


class TestGetTranscriber(unittest.TestCase):
    """Resolver falls back to Gemini when no VOICE provider is configured."""

    def test_default_is_gemini(self):
        from openbench.intelligence.transcription import GeminiTranscriber, get_transcriber

        # No VOICE provider configured in a fresh service → Gemini default.
        with patch("openbench.core.providers.get_provider_service") as svc:
            svc.return_value.resolve.side_effect = ValueError("no default")
            transcriber = get_transcriber()
        self.assertIsInstance(transcriber, GeminiTranscriber)
        self.assertEqual(transcriber.provider_name, "gemini")

    def test_registered_in_voice_registry(self):
        import openbench.intelligence.transcription  # noqa: F401  (triggers registration)
        from openbench.core.registry import TranscriptionRegistry

        cls = TranscriptionRegistry.get("voice", "gemini")
        self.assertIsNotNone(cls)


if __name__ == "__main__":
    unittest.main()
