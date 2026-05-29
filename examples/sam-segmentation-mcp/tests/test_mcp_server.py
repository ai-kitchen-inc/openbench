from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_ROOT))

from app.config import AppConfig
from app.service import SAM3ConceptCountingService, SAM3ModelNotAvailableError
from app.tool_schemas import COUNT_OBJECTS_WITH_SAM3_SCHEMA
from scripts.download_sam3_weights import main as download_sam3_weights


def _config(tmp_path, *, allowed_roots=None) -> AppConfig:
    return AppConfig(
        sam3_model_path=tmp_path / "models" / "sam3.pt",
        sam3_conf=0.25,
        sam3_half=False,
        sam3_device="cpu",
        sam3_verbose=False,
        allowed_image_roots=list(allowed_roots or []),
        max_image_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        return_overlay_default=False,
    )


def _touch_weights(config: AppConfig) -> None:
    config.sam3_model_path.parent.mkdir(parents=True, exist_ok=True)
    config.sam3_model_path.write_bytes(b"fake sam3 weights")


def _png_bytes() -> bytes:
    image = Image.new("RGB", (8, 6), "white")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class FakeMasks:
    def __init__(self, data):
        self.data = data


class FakeBoxes:
    xyxy = np.array([[1, 1, 4, 4], [5, 0, 7, 2], [0, 0, 1, 1]], dtype=float)
    conf = np.array([0.91, 0.82, 0.1], dtype=float)


class FakeResult:
    def __init__(self, masks):
        self.masks = masks
        self.boxes = FakeBoxes()


class FakePredictor:
    def __init__(self, result):
        self.result = result
        self.overrides = {}
        self.args = SimpleNamespace(conf=0.25)
        self.set_image_calls = []
        self.text_calls = []

    def set_image(self, image_path):
        assert Path(image_path).exists()
        self.set_image_calls.append(image_path)

    def __call__(self, *, text):
        self.text_calls.append(text)
        return [self.result]


def test_fastmcp_server_builds_when_sdk_is_installed():
    pytest.importorskip("mcp.server.fastmcp")

    from app.mcp_server import build_mcp

    server = build_mcp()

    assert server.name == "sam_segmentation_mcp"


def test_input_validation_rejects_missing_or_empty_concept(tmp_path):
    config = _config(tmp_path)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: None)
    image64 = base64.b64encode(_png_bytes()).decode("ascii")

    with pytest.raises(ValueError, match="concept is required"):
        service.count_objects_with_sam3(concept="", image_base64=image64)
    with pytest.raises(ValueError, match="concept is required"):
        service.count_objects_with_sam3(concept="   ", image_base64=image64)


def test_input_validation_rejects_zero_or_multiple_sources(tmp_path):
    config = _config(tmp_path)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: None)

    with pytest.raises(ValueError, match="exactly one"):
        service.count_objects_with_sam3(concept="dog")

    image64 = base64.b64encode(_png_bytes()).decode("ascii")
    with pytest.raises(ValueError, match="exactly one"):
        service.count_objects_with_sam3(
            concept="dog",
            image_path="a.png",
            image_base64=image64,
        )


def test_invalid_base64_is_clear_error(tmp_path):
    config = _config(tmp_path)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: None)

    with pytest.raises(ValueError, match="valid base64"):
        service.count_objects_with_sam3(concept="dog", image_base64="not image bytes")


def test_missing_sam3_weights_is_clear_setup_error(tmp_path):
    config = _config(tmp_path)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: None)
    image64 = base64.b64encode(_png_bytes()).decode("ascii")

    with pytest.raises(SAM3ModelNotAvailableError, match="requires sam3.pt"):
        service.count_objects_with_sam3(concept="dog", image_base64=image64)


def test_successful_sam3_counting_counts_filtered_masks_and_metadata(tmp_path):
    data = np.zeros((3, 6, 8), dtype=float)
    data[0, 1:4, 1:4] = 1
    data[1, 0:2, 5:7] = 1
    data[2, 0:1, 0:1] = 1
    fake_predictor = FakePredictor(FakeResult(FakeMasks(data)))
    config = _config(tmp_path)
    _touch_weights(config)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: fake_predictor)
    image64 = base64.b64encode(_png_bytes()).decode("ascii")

    result = service.count_objects_with_sam3(
        concept="dog",
        image_base64=image64,
        conf=0.5,
        min_area_pixels=4,
    )

    assert result["concept"] == "dog"
    assert result["count"] == 2
    assert result["mask_count"] == 2
    assert result["model"] == "sam3"
    assert result["model_path"].endswith("sam3.pt")
    assert result["image_width"] == 8
    assert result["image_height"] == 6
    assert result["segments"][0]["area_pixels"] == 9
    assert result["segments"][0]["bbox"] == [1, 1, 4, 4]
    assert result["segments"][0]["confidence"] == 0.91
    assert "Filtered 1 SAM 3 masks" in result["warnings"][0]
    assert fake_predictor.text_calls == [["dog"]]
    assert fake_predictor.args.conf == 0.5


def test_predictor_is_reused_across_requests(tmp_path):
    data = np.zeros((1, 6, 8), dtype=float)
    data[0, 1:4, 1:4] = 1
    fake_predictor = FakePredictor(FakeResult(FakeMasks(data)))
    created = []
    config = _config(tmp_path)
    _touch_weights(config)

    def factory(overrides):
        created.append(overrides)
        return fake_predictor

    service = SAM3ConceptCountingService(config, predictor_factory=factory)
    image64 = base64.b64encode(_png_bytes()).decode("ascii")

    service.count_objects_with_sam3(concept="dog", image_base64=image64)
    service.count_objects_with_sam3(concept="person", image_base64=image64)

    assert len(created) == 1
    assert fake_predictor.text_calls == [["dog"], ["person"]]


def test_missing_masks_returns_zero_with_warning(tmp_path):
    fake_predictor = FakePredictor(FakeResult(None))
    config = _config(tmp_path)
    _touch_weights(config)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: fake_predictor)
    image64 = base64.b64encode(_png_bytes()).decode("ascii")

    result = service.count_objects_with_sam3(concept="dog", image_base64=image64)

    assert result["concept"] == "dog"
    assert result["count"] == 0
    assert result["mask_count"] == 0
    assert result["model"] == "sam3"
    assert result["segments"] == []
    assert result["warnings"] == ["No matching SAM 3 masks were found for the requested concept."]


def test_return_overlay_is_opt_in(tmp_path):
    data = np.zeros((1, 6, 8), dtype=float)
    data[0, 1:4, 1:4] = 1
    fake_predictor = FakePredictor(FakeResult(FakeMasks(data)))
    config = _config(tmp_path)
    _touch_weights(config)
    service = SAM3ConceptCountingService(config, predictor_factory=lambda _: fake_predictor)
    image64 = base64.b64encode(_png_bytes()).decode("ascii")

    result = service.count_objects_with_sam3(
        concept="dog",
        image_base64=image64,
        return_overlay=True,
    )

    assert result["overlay_image_base64"]


def test_public_schema_is_sam3_only():
    dumped = str(COUNT_OBJECTS_WITH_SAM3_SCHEMA)

    assert COUNT_OBJECTS_WITH_SAM3_SCHEMA["name"] == "count_objects_with_sam3"
    assert "concept" in COUNT_OBJECTS_WITH_SAM3_SCHEMA["parameters"]["required"]
    assert "model" not in COUNT_OBJECTS_WITH_SAM3_SCHEMA["parameters"]["properties"]
    assert "image_url" not in COUNT_OBJECTS_WITH_SAM3_SCHEMA["parameters"]["properties"]
    assert "sam_b.pt" not in dumped
    assert "sam_l.pt" not in dumped
    assert "sam2" not in dumped
    assert "FastSAM" not in dumped
    assert "mobile_sam" not in dumped


def test_download_script_copies_local_weights(tmp_path, monkeypatch):
    source = tmp_path / "weights" / "sam3.pt"
    output = tmp_path / "models" / "sam3.pt"
    source.parent.mkdir()
    source.write_bytes(b"fake weights")

    monkeypatch.setenv("SAM3_LOCAL_WEIGHTS", str(source))
    monkeypatch.setenv("SAM3_MODEL_PATH", str(output))
    monkeypatch.setenv("SAM3_PREINSTALL", "required")

    assert download_sam3_weights() == 0
    assert output.read_bytes() == b"fake weights"


def test_dockerfile_installs_ultralytics_clip_dependency():
    dockerfile = (EXAMPLE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    requirements = (EXAMPLE_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "pip uninstall clip -y || true" in dockerfile
    assert "git+https://github.com/ultralytics/CLIP.git" in dockerfile
    assert "import clip, timm; print('SAM 3 CLIP and timm dependencies available')" in dockerfile
    assert dockerfile.count("git+https://github.com/ultralytics/CLIP.git") == 2
    assert "timm>=1.0" in requirements
