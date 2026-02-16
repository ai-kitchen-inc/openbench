"""Tests for MediaRenderer."""

import unittest

from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.media import MediaRenderer


class TestMediaRendererRegistry(unittest.TestCase):
    """Tests for MediaRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("media" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("media", "default")
        self.assertIsInstance(renderer, MediaRenderer)


class TestMediaRenderer(unittest.TestCase):
    """Tests for MediaRenderer."""

    def setUp(self):
        self.renderer = MediaRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "media")

    # -- detect --

    def test_detect_image(self):
        self.assertTrue(
            self.renderer.detect({"mediaType": "image", "src": "https://example.com/img.jpg"})
        )

    def test_detect_video(self):
        self.assertTrue(
            self.renderer.detect({"mediaType": "video", "src": "https://example.com/vid.mp4"})
        )

    def test_detect_audio(self):
        self.assertTrue(
            self.renderer.detect({"mediaType": "audio", "src": "https://example.com/song.mp3"})
        )

    def test_detect_missing_src(self):
        self.assertFalse(self.renderer.detect({"mediaType": "image"}))

    def test_detect_missing_media_type(self):
        self.assertFalse(self.renderer.detect({"src": "https://example.com/img.jpg"}))

    def test_detect_invalid_media_type(self):
        self.assertFalse(
            self.renderer.detect({"mediaType": "pdf", "src": "https://example.com/doc.pdf"})
        )

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("some string"))
        self.assertFalse(self.renderer.detect(42))
        self.assertFalse(self.renderer.detect(None))

    def test_detect_empty_dict(self):
        self.assertFalse(self.renderer.detect({}))

    def test_detect_does_not_clash_with_chart(self):
        self.assertFalse(self.renderer.detect({"type": "bar", "data": []}))

    def test_detect_does_not_clash_with_file(self):
        self.assertFalse(self.renderer.detect({"name": "report.pdf", "url": "https://..."}))

    # -- render image --

    def test_render_image_basic(self):
        content = {"mediaType": "image", "src": "https://example.com/img.jpg"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        img = components[0]
        self.assertEqual(img.component, "Image")
        self.assertEqual(img.properties["src"], "https://example.com/img.jpg")

    def test_render_image_with_alt(self):
        content = {
            "mediaType": "image",
            "src": "https://example.com/img.jpg",
            "alt": "A beautiful sunset",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["alt"], "A beautiful sunset")

    def test_render_image_caption_as_alt(self):
        content = {
            "mediaType": "image",
            "src": "https://example.com/img.jpg",
            "caption": "Nature photo",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["alt"], "Nature photo")

    def test_render_image_with_dimensions(self):
        content = {
            "mediaType": "image",
            "src": "https://example.com/img.jpg",
            "width": "400px",
            "height": "300px",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(components[0].properties["width"], "400px")
        self.assertEqual(components[0].properties["height"], "300px")

    # -- render video --

    def test_render_video_basic(self):
        content = {"mediaType": "video", "src": "https://example.com/vid.mp4"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        vid = components[0]
        self.assertEqual(vid.component, "Video")
        self.assertEqual(vid.properties["src"], "https://example.com/vid.mp4")

    def test_render_video_with_props(self):
        content = {
            "mediaType": "video",
            "src": "https://example.com/vid.mp4",
            "title": "Demo Video",
            "poster": "https://example.com/thumb.jpg",
            "autoplay": True,
            "width": "640px",
            "height": "360px",
        }
        components = self.renderer.render(content, surface_id="s1")
        # Title text + video component
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "Demo Video")
        vid = components[1]
        self.assertEqual(vid.component, "Video")
        self.assertEqual(vid.properties["title"], "Demo Video")
        self.assertEqual(vid.properties["poster"], "https://example.com/thumb.jpg")
        self.assertTrue(vid.properties["autoplay"])
        self.assertEqual(vid.properties["width"], "640px")
        self.assertEqual(vid.properties["height"], "360px")

    # -- render audio --

    def test_render_audio_basic(self):
        content = {"mediaType": "audio", "src": "https://example.com/song.mp3"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        audio = components[0]
        self.assertEqual(audio.component, "AudioPlayer")
        self.assertEqual(audio.properties["src"], "https://example.com/song.mp3")

    def test_render_audio_with_props(self):
        content = {
            "mediaType": "audio",
            "src": "https://example.com/song.mp3",
            "title": "Podcast Episode",
            "autoplay": False,
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "Podcast Episode")
        audio = components[1]
        self.assertEqual(audio.component, "AudioPlayer")
        self.assertEqual(audio.properties["title"], "Podcast Episode")
        self.assertFalse(audio.properties["autoplay"])

    # -- render with title --

    def test_render_with_title(self):
        content = {
            "mediaType": "image",
            "src": "https://example.com/img.jpg",
            "title": "My Image",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0].component, "Text")
        self.assertEqual(components[0].properties["text"], "My Image")
        self.assertEqual(components[0].properties["variant"], "h4")
        self.assertEqual(components[1].component, "Image")

    def test_render_without_title(self):
        content = {"mediaType": "image", "src": "https://example.com/img.jpg"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].component, "Image")

    # -- unique IDs --

    def test_unique_ids(self):
        content = {
            "mediaType": "image",
            "src": "https://example.com/img.jpg",
            "title": "Test",
        }
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)))

    def test_id_prefixes(self):
        content = {
            "mediaType": "video",
            "src": "https://example.com/vid.mp4",
            "title": "T",
        }
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("media-title-"))
        self.assertTrue(components[1].id.startswith("video-"))

    def test_image_id_prefix(self):
        content = {"mediaType": "image", "src": "https://example.com/img.jpg"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("image-"))

    def test_audio_id_prefix(self):
        content = {"mediaType": "audio", "src": "https://example.com/song.mp3"}
        components = self.renderer.render(content, surface_id="s1")
        self.assertTrue(components[0].id.startswith("audio-"))


if __name__ == "__main__":
    unittest.main()
