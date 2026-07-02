"""Speech-to-text transcription providers.

Defines the concrete :class:`GeminiTranscriber` (Gemini native audio) plus a
:func:`get_transcriber` resolver. Audio extractors depend only on the abstract
:class:`~openbench.core.abstractions.TranscriptionProvider`, so swapping the
backend (Whisper, OpenAI-compatible, cloud STT) is a registration change — no
extractor edits.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from openbench.core.abstractions import TranscriptionProvider
from openbench.core.providers import ProviderType, get_provider_service
from openbench.core.registry import TranscriptionRegistry

logger = logging.getLogger(__name__)

_TRANSCRIBE_PROMPT = (
    "Transcribe the following audio verbatim. Output only the transcript text, "
    "with no commentary, labels, or timestamps."
)

# Audio files <= this size are sent inline; larger go through the Files API.
_INLINE_AUDIO_LIMIT = 18 * 1024 * 1024

_AUDIO_EXT_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".mp4": "audio/mp4",
}


class GeminiTranscriber(TranscriptionProvider):
    """Transcribe audio with Gemini's native audio understanding."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        **kwargs,
    ):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model
        self._client = None

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError:
                raise ImportError(
                    "google-genai package required for GeminiTranscriber. "
                    "Install with: pip install google-genai"
                ) from None
            if not self.api_key:
                raise ValueError(
                    "Google API key required. Set GOOGLE_API_KEY or pass api_key."
                )
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def transcribe(self, audio: str | bytes, model: str = "", **params) -> str:
        """Transcribe audio (file path or raw bytes) to text."""
        from google.genai import types

        client = self._get_client()
        model = model or self.model

        if isinstance(audio, bytes):
            mime = params.get("mime_type")
            if not mime:
                raise ValueError("mime_type is required when transcribing raw bytes.")
            audio_part = types.Part.from_bytes(data=audio, mime_type=mime)
        else:
            path = Path(audio)
            mime = params.get("mime_type") or _AUDIO_EXT_MIME.get(
                path.suffix.lower(), "audio/mpeg"
            )
            size = path.stat().st_size
            if size <= _INLINE_AUDIO_LIMIT:
                audio_part = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime)
            else:
                uploaded = self._upload(client, str(path))
                audio_part = types.Part.from_uri(
                    file_uri=uploaded.uri,
                    mime_type=getattr(uploaded, "mime_type", mime),
                )

        response = client.models.generate_content(
            model=model,
            contents=[_TRANSCRIBE_PROMPT, audio_part],
        )
        return (getattr(response, "text", "") or "").strip()

    @staticmethod
    def _upload(client: Any, path: str) -> Any:
        import time

        uploaded = client.files.upload(file=path)
        for _ in range(30):
            state = getattr(getattr(uploaded, "state", None), "name", None)
            if state != "PROCESSING":
                break
            time.sleep(1)
            uploaded = client.files.get(name=uploaded.name)
        return uploaded


# Register so config-driven VOICE provider resolution can find it.
TranscriptionRegistry.register(
    "voice",
    "gemini",
    description="Google Gemini native audio transcription",
)(GeminiTranscriber)


def get_transcriber(provider_name: str | None = None) -> TranscriptionProvider:
    """Resolve a transcription provider.

    Prefers a configured VOICE provider; falls back to Gemini-from-env so audio
    works out of the box when only an LLM provider is configured. The audio
    extractor calls this and depends only on the returned abstract interface.
    """
    service = get_provider_service()
    try:
        return service.resolve(ProviderType.VOICE, name=provider_name)
    except Exception as exc:
        logger.debug("No VOICE provider configured (%s); defaulting to Gemini.", exc)
        return GeminiTranscriber()
