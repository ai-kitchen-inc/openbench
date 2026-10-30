"""VLM-backed image reading for uploads: OCR transcript + short visual summary.

The upload pipeline used to run Docling's full page pipeline (layout model +
OCR engine) on every image, ~20 s per image on the 2-vCPU production worker.
A single vision-model call returns the same transcript plus a description in
a few seconds and also handles photos with no text at all, which Docling
rejected as "no OCR text". Docling stays as the fallback when no VLM is
reachable (no key, provider down, ``GENERAL_CHAT_IMAGE_READER=docling``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

READER_ENV = "GENERAL_CHAT_IMAGE_READER"
MODE_VLM = "vlm"
MODE_DOCLING = "docling"

DETECTED_HEADING = "### Detected text"
SUMMARY_HEADING = "### Visual summary"
_NO_TEXT_MARKERS = {"(none)", "none", "(no text)", "no text", "-"}

READ_PROMPT = (
    "Read this image for a document search index.\n"
    f"First, under the heading '{DETECTED_HEADING}', transcribe ALL visible text "
    "verbatim, keeping the reading order and line breaks; write '(none)' if the "
    "image contains no text.\n"
    f"Then, under the heading '{SUMMARY_HEADING}', describe what the image shows in "
    "one or two sentences, from visible evidence only. No other commentary."
)

_DEFAULT_MODEL = "gemini-2.5-flash"
_DEFAULT_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class ImageReadResult:
    """What a vision model read from one image."""

    ocr_text: str
    description: str
    provider: str
    model: str


def parse_read_response(text: str) -> tuple[str, str]:
    """Split a model response into ``(ocr_text, summary)``.

    Tolerant of a missing or reordered heading: with no headings the whole
    response counts as transcript, and a lone "(none)" transcript is empty.
    """
    body = (text or "").strip()
    if not body:
        return "", ""
    lower = body.lower()
    detected_at = lower.find(DETECTED_HEADING.lower())
    summary_at = lower.find(SUMMARY_HEADING.lower())
    if detected_at < 0 and summary_at < 0:
        return _clean_transcript(body), ""
    if detected_at < 0:
        return "", body[summary_at + len(SUMMARY_HEADING) :].strip()
    if summary_at < 0:
        return _clean_transcript(body[detected_at + len(DETECTED_HEADING) :]), ""
    if detected_at < summary_at:
        ocr = body[detected_at + len(DETECTED_HEADING) : summary_at]
        summary = body[summary_at + len(SUMMARY_HEADING) :]
    else:
        summary = body[summary_at + len(SUMMARY_HEADING) : detected_at]
        ocr = body[detected_at + len(DETECTED_HEADING) :]
    return _clean_transcript(ocr), summary.strip()


def _clean_transcript(text: str) -> str:
    cleaned = text.strip()
    if cleaned.lower() in _NO_TEXT_MARKERS:
        return ""
    return cleaned


class VLMImageReader:
    """Read an image with any :class:`~openbench.core.abstractions.VLMProvider`."""

    def __init__(
        self,
        provider: Any,
        *,
        model: str,
        temperature: float = 0.0,
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self._provider = provider
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    @property
    def provider_name(self) -> str:
        return str(getattr(self._provider, "provider_name", "") or "vlm")

    def read(self, path: str) -> ImageReadResult:
        """Return the transcript and summary for the image at ``path``.

        Raises whatever the provider raises (network, auth, quota): the
        caller decides whether to fall back to local OCR.
        """
        response = self._provider.generate(
            prompt=READ_PROMPT,
            images=[path],
            model=self.model,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        ocr_text, summary = parse_read_response(getattr(response, "text", "") or "")
        return ImageReadResult(
            ocr_text=ocr_text,
            description=summary,
            provider=self.provider_name,
            model=str(getattr(response, "model", "") or self.model),
        )


def image_reader_mode() -> str:
    """``vlm`` (default) or ``docling`` from ``GENERAL_CHAT_IMAGE_READER``."""
    raw = (os.getenv(READER_ENV) or MODE_VLM).strip().lower()
    return MODE_DOCLING if raw == MODE_DOCLING else MODE_VLM


_UNSET = object()
_cached_reader: Any = _UNSET


def reset_image_reader() -> None:
    """Forget the cached reader (tests and env changes)."""
    global _cached_reader
    _cached_reader = _UNSET


def get_image_reader() -> VLMImageReader | None:
    """Resolve the process-wide image reader, or None to use Docling.

    Order: the provider the API configured for its vision stage
    (``general-chat-vlm`` in the provider service, so a local Gemma/Ollama
    VLM is honoured in-process), then Gemini straight from the environment
    key — the worker never configures providers, so this is its path.
    Returns None when the mode is ``docling`` or no VLM can be built.
    """
    global _cached_reader
    if _cached_reader is not _UNSET:
        return _cached_reader
    _cached_reader = _build_reader()
    return _cached_reader


def _build_reader() -> VLMImageReader | None:
    if image_reader_mode() != MODE_VLM:
        return None
    provider_name, model = _vlm_selection()
    temperature = _env_float("GENERAL_CHAT_IMAGE_READER_TEMPERATURE", 0.0)

    provider = _configured_provider(model, temperature)
    if provider is None and provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            from openbench.intelligence.vlm_providers import GeminiVLMProvider

            provider = GeminiVLMProvider(api_key=api_key, model=model, temperature=temperature)
    if provider is None:
        logger.info("No VLM available for image reading; uploads use Docling OCR")
        return None
    logger.info("Image reader: %s model=%s", getattr(provider, "provider_name", "vlm"), model)
    return VLMImageReader(provider, model=model, temperature=temperature)


def _configured_provider(model: str, temperature: float) -> Any | None:
    """The API's own vision provider, when this process registered one."""
    try:
        from openbench.core.providers import ProviderType, get_provider_service

        return get_provider_service().resolve(
            ProviderType.VLM, name="general-chat-vlm", model=model, temperature=temperature
        )
    except Exception:
        return None


def _vlm_selection() -> tuple[str, str]:
    """``(provider, model)`` using the same env the chat's vision stage reads."""
    try:
        from general_chat.agent import _resolve_vlm_selection

        provider, model, _requested = _resolve_vlm_selection()
        return provider or "gemini", model or _DEFAULT_MODEL
    except Exception:
        model = (
            os.getenv("GENERAL_CHAT_VLM_MODEL") or os.getenv("OPENBENCH_VLM_MODEL") or ""
        ).strip()
        return "gemini", model or _DEFAULT_MODEL


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


__all__ = [
    "DETECTED_HEADING",
    "ImageReadResult",
    "READER_ENV",
    "READ_PROMPT",
    "SUMMARY_HEADING",
    "VLMImageReader",
    "get_image_reader",
    "image_reader_mode",
    "parse_read_response",
    "reset_image_reader",
]
