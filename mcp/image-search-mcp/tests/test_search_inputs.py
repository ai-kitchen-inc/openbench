from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image

from app.search import load_image_base64, load_image_path


def _png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), color=(255, 0, 0))
    handle = BytesIO()
    image.save(handle, format="PNG")
    return handle.getvalue()


def test_load_image_path_supports_png(tmp_path):
    path = tmp_path / "query.png"
    path.write_bytes(_png_bytes())

    image = load_image_path(str(path))

    assert image.mode == "RGB"
    assert image.size == (4, 4)


def test_load_image_base64_supports_data_url():
    encoded = base64.b64encode(_png_bytes()).decode("ascii")

    image = load_image_base64(f"data:image/png;base64,{encoded}")

    assert image.mode == "RGB"
    assert image.size == (4, 4)


def test_load_image_path_rejects_missing_file():
    with pytest.raises(ValueError, match="does not exist"):
        load_image_path("missing.png")


def test_load_image_base64_rejects_malformed_input():
    with pytest.raises(ValueError, match="valid base64"):
        load_image_base64("not valid")
