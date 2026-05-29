"""Application service layer for SAM 3 concept counting."""

from __future__ import annotations

import base64
import logging
import tempfile
import threading
from contextlib import contextmanager
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
from PIL import Image, ImageDraw

from app.config import AppConfig
from app.image_io import LoadedImage, load_image_base64, load_image_path

logger = logging.getLogger(__name__)

PredictorFactory = Callable[[dict[str, Any]], Any]

MISSING_MODEL_MESSAGE = (
    "SAM 3 weights were not found. This server requires sam3.pt. "
    "Download sam3.pt after receiving access from the SAM 3 Hugging Face model page, "
    "then copy it to weights/sam3.pt before building or mount it at /models/sam3.pt. "
    "No fallback model is available because this server is SAM 3 only."
)


class SAM3ModelNotAvailableError(RuntimeError):
    """Raised when SAM 3 weights are missing."""


def _default_predictor_factory(overrides: dict[str, Any]) -> Any:
    try:
        from ultralytics.models.sam import SAM3SemanticPredictor
    except ImportError as exc:
        raise ImportError(
            "ultralytics>=8.3.237 is required to run SAM 3 concept counting"
        ) from exc
    return SAM3SemanticPredictor(overrides=overrides)


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _bbox_from_mask(mask: np.ndarray) -> list[int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    if mask.shape == (height, width):
        return mask.astype(bool)
    image = Image.fromarray(mask.astype("uint8") * 255, mode="L")
    resized = image.resize((width, height), Image.Resampling.NEAREST)
    return np.asarray(resized) > 0


def _optional_array(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    try:
        return _to_numpy(value)
    except Exception:
        return None


@contextmanager
def _image_file_for_predictor(loaded: LoadedImage) -> Iterator[str]:
    """Yield a filesystem path suitable for ``SAM3SemanticPredictor.set_image``."""
    source_path = loaded.metadata.get("image_path")
    if isinstance(source_path, str) and source_path:
        yield source_path
        return

    suffix = ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        temp_path = Path(tmp.name)
        loaded.image.save(tmp, format="PNG")
    try:
        yield str(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


class SAM3ConceptCountingService:
    """Coordinates image loading, SAM 3 inference, and concept count metadata."""

    def __init__(
        self,
        config: AppConfig,
        *,
        predictor_factory: PredictorFactory | None = None,
    ):
        self.config = config
        self.config.ensure_directories()
        self._predictor_factory = predictor_factory or _default_predictor_factory
        self._predictor: Any | None = None
        self._predictor_lock = threading.Lock()

    def _load_input_image(
        self,
        *,
        image_path: str | None,
        image_base64: str | None,
        mime_type: str | None,
    ) -> LoadedImage:
        provided = [
            image_path is not None,
            image_base64 is not None,
        ]
        if sum(provided) != 1:
            raise ValueError("Provide exactly one image input: image_path or image_base64.")
        if image_path is not None:
            return load_image_path(
                image_path,
                allowed_roots=self.config.allowed_image_roots,
                max_bytes=self.config.max_image_bytes,
                max_pixels=self.config.max_image_pixels,
            )
        assert image_base64 is not None
        return load_image_base64(
            image_base64,
            mime_type=mime_type,
            max_bytes=self.config.max_image_bytes,
            max_pixels=self.config.max_image_pixels,
        )

    def _predictor_overrides(self, conf: float) -> dict[str, Any]:
        overrides: dict[str, Any] = {
            "conf": conf,
            "task": "segment",
            "mode": "predict",
            "model": str(self.config.sam3_model_path),
            "half": self.config.sam3_half,
            "verbose": self.config.sam3_verbose,
        }
        if self.config.sam3_device:
            overrides["device"] = self.config.sam3_device
        return overrides

    def _get_predictor(self, conf: float) -> Any:
        if not self.config.sam3_model_path.exists():
            raise SAM3ModelNotAvailableError(
                f"{MISSING_MODEL_MESSAGE} Expected path: {self.config.sam3_model_path}"
            )
        if self._predictor is None:
            logger.info("loading SAM 3 predictor: %s", self.config.sam3_model_path)
            self._predictor = self._predictor_factory(self._predictor_overrides(conf))
        return self._predictor

    def count_objects_with_sam3(
        self,
        *,
        concept: str,
        image_path: str | None = None,
        image_base64: str | None = None,
        mime_type: str | None = None,
        conf: float | None = None,
        min_area_pixels: int | None = None,
        return_segments: bool = True,
        return_overlay: bool | None = None,
    ) -> dict[str, Any]:
        """Segment all instances of a text concept with SAM 3 and count masks."""
        normalized_concept = concept.strip() if isinstance(concept, str) else ""
        if not normalized_concept:
            raise ValueError("concept is required and must be a non-empty string.")
        threshold = self.config.sam3_conf if conf is None else float(conf)
        if not 0 <= threshold <= 1:
            raise ValueError("conf must be between 0 and 1.")
        min_area = int(min_area_pixels or 0)
        if min_area < 0:
            raise ValueError("min_area_pixels must be zero or positive.")

        loaded = self._load_input_image(
            image_path=image_path,
            image_base64=image_base64,
            mime_type=mime_type,
        )
        width, height = loaded.image.size

        with _image_file_for_predictor(loaded) as predictor_image_path:
            predictor = self._get_predictor(threshold)
            logger.info(
                "starting SAM 3 concept inference: concept=%s source=%s size=%sx%s",
                normalized_concept,
                loaded.metadata.get("source"),
                width,
                height,
            )
            with self._predictor_lock:
                _set_predictor_conf(predictor, threshold)
                predictor.set_image(predictor_image_path)
                results = predictor(text=[normalized_concept])
            logger.info("finished SAM 3 concept inference: concept=%s", normalized_concept)

        segments, overlay_masks, warnings = _segments_from_results(
            results=results,
            width=width,
            height=height,
            min_area=min_area,
            return_segments=return_segments,
        )
        if not segments:
            warnings.append("No matching SAM 3 masks were found for the requested concept.")

        payload: dict[str, Any] = {
            "concept": normalized_concept,
            "count": len(segments),
            "mask_count": len(segments),
            "model": "sam3",
            "model_path": str(self.config.sam3_model_path),
            "image_width": width,
            "image_height": height,
            "segments": segments if return_segments else [],
            "warnings": warnings,
            "source": loaded.metadata,
        }
        if return_overlay if return_overlay is not None else self.config.return_overlay_default:
            payload["overlay_image_base64"] = _overlay_base64(loaded.image, overlay_masks)
        return payload

    def service_info(self) -> dict[str, Any]:
        """Return SAM 3 service health and configuration metadata."""
        return {
            "model": "sam3",
            "model_path": str(self.config.sam3_model_path),
            "model_cached": self.config.sam3_model_path.exists(),
            "sam3_device": self.config.sam3_device,
            "sam3_conf": self.config.sam3_conf,
            "sam3_half": self.config.sam3_half,
            "max_image_bytes": self.config.max_image_bytes,
            "max_image_pixels": self.config.max_image_pixels,
            "allowed_image_roots": [str(path) for path in self.config.allowed_image_roots],
            "predictor_loaded": self._predictor is not None,
        }


def _segments_from_results(
    *,
    results: Any,
    width: int,
    height: int,
    min_area: int,
    return_segments: bool,
) -> tuple[list[dict[str, Any]], list[np.ndarray], list[str]]:
    result = results[0] if isinstance(results, (list, tuple)) and results else results
    masks_obj = getattr(result, "masks", None)
    warnings: list[str] = []
    if masks_obj is None or getattr(masks_obj, "data", None) is None:
        return [], [], warnings

    mask_data = _to_numpy(masks_obj.data)
    if mask_data.ndim == 2:
        mask_data = mask_data[None, :, :]
    boxes_obj = getattr(result, "boxes", None)
    boxes = _optional_array(getattr(boxes_obj, "xyxy", None))
    confidences = _optional_array(getattr(boxes_obj, "conf", None))

    segments: list[dict[str, Any]] = []
    overlay_masks: list[np.ndarray] = []
    filtered_count = 0
    for index, raw_mask in enumerate(mask_data):
        mask_bool = _resize_mask(raw_mask > 0.5, width, height)
        area = int(mask_bool.sum())
        if area < min_area:
            filtered_count += 1
            continue
        bbox = None
        if boxes is not None and index < len(boxes):
            bbox = [int(round(float(value))) for value in boxes[index][:4]]
        if bbox is None:
            bbox = _bbox_from_mask(mask_bool)
        if bbox is None:
            continue
        confidence = None
        if confidences is not None and index < len(confidences):
            confidence = round(float(confidences[index]), 6)
        segment: dict[str, Any] = {
            "id": len(segments) + 1,
            "area_pixels": area,
            "bbox": bbox,
            "confidence": confidence,
        }
        if return_segments:
            segments.append(segment)
        else:
            segments.append({"id": segment["id"]})
        overlay_masks.append(mask_bool)

    if filtered_count:
        warnings.append(
            f"Filtered {filtered_count} SAM 3 masks below min_area_pixels={min_area}."
        )
    return segments, overlay_masks, warnings


def _set_predictor_conf(predictor: Any, conf: float) -> None:
    args = getattr(predictor, "args", None)
    if args is not None and hasattr(args, "conf"):
        setattr(args, "conf", conf)
        return
    overrides = getattr(predictor, "overrides", None)
    if isinstance(overrides, dict):
        overrides["conf"] = conf


def _overlay_base64(image: Image.Image, masks: list[np.ndarray]) -> str:
    colors = [
        (0, 114, 178, 90),
        (213, 94, 0, 90),
        (0, 158, 115, 90),
        (204, 121, 167, 90),
        (230, 159, 0, 90),
        (86, 180, 233, 90),
    ]
    base = image.convert("RGBA")
    for index, mask in enumerate(masks):
        color = colors[index % len(colors)]
        mask_image = Image.fromarray(mask.astype("uint8") * color[3], mode="L")
        layer = Image.new("RGBA", base.size, color[:3] + (0,))
        layer.putalpha(mask_image)
        base.alpha_composite(layer)
    draw = ImageDraw.Draw(base)
    for index, mask in enumerate(masks, start=1):
        bbox = _bbox_from_mask(mask)
        if bbox is None:
            continue
        draw.rectangle(bbox, outline=(255, 255, 255, 210), width=2)
        draw.text((bbox[0] + 2, bbox[1] + 2), str(index), fill=(255, 255, 255, 255))
    out = BytesIO()
    base.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


@lru_cache(maxsize=1)
def get_service() -> SAM3ConceptCountingService:
    """Return a process-wide service configured from the environment."""
    return SAM3ConceptCountingService(AppConfig.from_env())
