"""Tests for provider-neutral multimodal message channel (Gemini translation)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.core.abstractions import MediaContent
from openbench.intelligence.base import AgentMemory, Message, MessageRole

try:
    import google.genai  # noqa: F401

    from openbench.intelligence.llm_providers import GeminiLLMProvider

    _HAS_GENAI = True
except ImportError:
    _HAS_GENAI = False


class TestMediaContent(unittest.TestCase):
    """The neutral media reference round-trips through plain dicts."""

    def test_to_from_dict(self):
        m = MediaContent(type="image", mime_type="image/png", path="/x/a.png")
        d = m.to_dict()
        self.assertEqual(d["type"], "image")
        self.assertEqual(d["mime_type"], "image/png")
        self.assertEqual(d["path"], "/x/a.png")
        self.assertNotIn("uri", d)  # absent fields omitted
        back = MediaContent.from_dict(d)
        self.assertEqual(back, m)

    def test_message_to_dict_includes_media(self):
        msg = Message(
            role=MessageRole.USER,
            content="look",
            media=[MediaContent(type="image", mime_type="image/png", path="/x/a.png")],
        )
        d = msg.to_dict()
        self.assertEqual(len(d["media"]), 1)
        self.assertEqual(d["media"][0]["type"], "image")

    def test_add_user_carries_media(self):
        mem = AgentMemory()
        mem.add_user("hi", media=[MediaContent(type="audio", mime_type="audio/mp3", path="/a.mp3")])
        msgs = mem.get_messages()
        self.assertIn("media", msgs[-1])
        self.assertEqual(msgs[-1]["media"][0]["mime_type"], "audio/mp3")

    def test_add_user_without_media_is_plain(self):
        mem = AgentMemory()
        mem.add_user("hi")
        self.assertNotIn("media", mem.get_messages()[-1])


@unittest.skipUnless(_HAS_GENAI, "google-genai not installed")
class TestGeminiMediaParts(unittest.TestCase):
    """_convert_messages translates neutral media into Gemini Parts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.img = Path(self.tmp) / "a.png"
        self.img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        self.provider = GeminiLLMProvider(api_key="test-key", model="gemini-2.5-flash")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _user_msg(self, media_type, mime, path):
        return [
            {
                "role": "user",
                "content": "describe this",
                "media": [{"type": media_type, "mime_type": mime, "path": str(path)}],
            }
        ]

    def test_image_inline_part_is_added(self):
        _, contents = self.provider._convert_messages(
            self._user_msg("image", "image/png", self.img), model="gemini-2.5-flash"
        )
        # text part + media part
        self.assertEqual(len(contents[0].parts), 2)

    def test_oversize_routes_to_files_api(self):
        # Force the inline limit to 0 so any file goes through the Files API.
        self.provider._INLINE_MEDIA_LIMIT = 0
        calls = {}

        class _Uploaded:
            uri = "https://files/abc"
            mime_type = "image/png"

        def _fake_upload(path, mime):
            calls["path"] = path
            return _Uploaded()

        self.provider._upload_via_files_api = _fake_upload  # type: ignore[assignment]
        _, contents = self.provider._convert_messages(
            self._user_msg("image", "image/png", self.img), model="gemini-2.5-flash"
        )
        self.assertEqual(len(contents[0].parts), 2)
        self.assertEqual(calls["path"], str(self.img))

    def test_unsupported_modality_falls_back_to_text(self):
        # gpt-4o is registered with supports_audio=False → audio dropped, only text.
        _, contents = self.provider._convert_messages(
            self._user_msg("audio", "audio/mpeg", self.img), model="gpt-4o"
        )
        self.assertEqual(len(contents[0].parts), 1)

    def test_missing_file_degrades_to_text(self):
        msgs = self._user_msg("image", "image/png", Path(self.tmp) / "nope.png")
        _, contents = self.provider._convert_messages(msgs, model="gemini-2.5-flash")
        self.assertEqual(len(contents[0].parts), 1)

    def test_plain_user_message_unchanged(self):
        _, contents = self.provider._convert_messages(
            [{"role": "user", "content": "hello"}], model="gemini-2.5-flash"
        )
        self.assertEqual(len(contents[0].parts), 1)


if __name__ == "__main__":
    unittest.main()
