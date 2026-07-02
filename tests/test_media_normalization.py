"""Tests for provider-agnostic media normalization helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openbench.utils.media import (
    is_svg,
    normalize_image,
    read_svg_text,
)

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import cairosvg  # noqa: F401

    _HAS_CAIROSVG = True
except ImportError:
    _HAS_CAIROSVG = False

_SVG = (
    '<?xml version="1.0"?>'
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10"/><text>hello svg</text></svg>'
)


class TestSvgHelpers(unittest.TestCase):
    """SVG detection + text read need no optional dependency."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_is_svg_by_extension(self):
        self.assertTrue(is_svg("logo.svg"))
        self.assertTrue(is_svg("logo.SVG"))

    def test_is_svg_by_mime(self):
        self.assertTrue(is_svg("x", "image/svg+xml"))
        self.assertFalse(is_svg("x.png", "image/png"))

    def test_read_svg_text(self):
        p = Path(self.tmp) / "a.svg"
        p.write_text(_SVG, encoding="utf-8")
        text = read_svg_text(p)
        self.assertIn("hello svg", text)


class TestNormalizeImage(unittest.TestCase):
    """normalize_image converts to a raster widely accepted downstream."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_native_raster_passthrough(self):
        """PNG/JPEG/WEBP return unchanged — no conversion attempted."""
        p = Path(self.tmp) / "a.png"
        p.write_bytes(b"fake-png")
        out_path, out_mime = normalize_image(p, "image/png")
        self.assertEqual(out_path, str(p))
        self.assertEqual(out_mime, "image/png")

    @unittest.skipUnless(_HAS_PIL, "Pillow not installed")
    def test_bmp_to_png(self):
        src = Path(self.tmp) / "a.bmp"
        Image.new("RGB", (4, 4), "red").save(src, format="BMP")
        out_path, out_mime = normalize_image(src, "image/bmp")
        self.assertTrue(out_path.endswith(".png"))
        self.assertTrue(Path(out_path).exists())
        self.assertEqual(out_mime, "image/png")

    @unittest.skipUnless(_HAS_PIL, "Pillow not installed")
    def test_tiff_to_png(self):
        src = Path(self.tmp) / "a.tiff"
        Image.new("RGB", (4, 4), "blue").save(src, format="TIFF")
        out_path, out_mime = normalize_image(src, "image/tiff")
        self.assertTrue(out_path.endswith(".png"))
        self.assertEqual(out_mime, "image/png")

    @unittest.skipUnless(_HAS_PIL, "Pillow not installed")
    def test_gif_first_frame_to_png(self):
        src = Path(self.tmp) / "a.gif"
        Image.new("P", (4, 4)).save(src, format="GIF")
        out_path, out_mime = normalize_image(src, "image/gif")
        self.assertTrue(out_path.endswith(".png"))
        self.assertEqual(out_mime, "image/png")

    @unittest.skipUnless(_HAS_CAIROSVG, "cairosvg not installed")
    def test_svg_to_png(self):
        src = Path(self.tmp) / "a.svg"
        src.write_text(_SVG, encoding="utf-8")
        out_path, out_mime = normalize_image(src, "image/svg+xml")
        self.assertTrue(out_path.endswith(".png"))
        self.assertEqual(out_mime, "image/png")


if __name__ == "__main__":
    unittest.main()
