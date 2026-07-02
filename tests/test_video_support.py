"""Tests for video understanding (text track + container transcode)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openbench.chat.files import FileContentExtractor, StoredFile
from openbench.core.abstractions import TranscriptionProvider


class _FakeTranscriber(TranscriptionProvider):
    @property
    def provider_name(self) -> str:
        return "fake"

    def transcribe(self, audio, model: str = "", **params) -> str:
        return "spoken words in the clip"


def _video_stored(path: Path) -> StoredFile:
    return StoredFile(
        id="file-v",
        name=path.name,
        path=str(path),
        mime_type="video/mp4",
        size_bytes=path.stat().st_size,
        stored_at="2026-01-01T00:00:00+00:00",
    )


class TestVideoExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.video = Path(self.tmp) / "clip.mp4"
        self.video.write_bytes(b"fake-video-bytes")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_video_transcript_from_audio_track(self):
        fake_wav = str(Path(self.tmp) / "clip.audio.wav")
        Path(fake_wav).write_bytes(b"RIFFfake")
        with (
            patch("openbench.utils.media.extract_audio_track", return_value=fake_wav),
            patch(
                "openbench.intelligence.transcription.get_transcriber",
                return_value=_FakeTranscriber(),
            ),
        ):
            text = FileContentExtractor().extract(_video_stored(self.video))
        self.assertIn("Transcript of clip.mp4", text)
        self.assertIn("spoken words", text)

    def test_video_without_audio_track(self):
        with patch("openbench.utils.media.extract_audio_track", return_value=None):
            text = FileContentExtractor().extract(_video_stored(self.video))
        self.assertIn("no audio track", text)


class TestEnsureVideoForGemini(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mp4_passthrough_no_transcode(self):
        from openbench.utils.media import ensure_video_for_gemini

        src = Path(self.tmp) / "a.mp4"
        src.write_bytes(b"x")
        out_path, out_mime = ensure_video_for_gemini(src, "video/mp4")
        self.assertEqual(out_path, str(src))
        self.assertEqual(out_mime, "video/mp4")

    def test_avi_triggers_transcode(self):
        from openbench.utils import media

        src = Path(self.tmp) / "a.avi"
        src.write_bytes(b"x")
        with patch.object(
            media, "transcode_video_to_mp4", return_value=str(src) + ".mp4"
        ) as mock_tc:
            out_path, out_mime = media.ensure_video_for_gemini(src, "video/x-msvideo")
        mock_tc.assert_called_once()
        self.assertTrue(out_path.endswith(".mp4"))
        self.assertEqual(out_mime, "video/mp4")


if __name__ == "__main__":
    unittest.main()
