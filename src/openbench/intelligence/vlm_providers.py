"""Concrete vision-language model provider implementations.

Gemma is backed by a local OpenAI-compatible chat-completions endpoint such as
Ollama, vLLM, or LM Studio. Gemini uses the google-genai SDK directly.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from openbench.core.abstractions import LLMResponse, VLMProvider

logger = logging.getLogger(__name__)


def _normalize_chat_completions_url(base_url: str) -> str:
    """Return a concrete OpenAI-compatible chat-completions endpoint."""
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/v1/chat/completions"


def _path_to_data_url(path: str) -> str:
    """Encode a local image path as a data URL."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Image file not found: {p}")
    mime_type = mimetypes.guess_type(p.name)[0] or "image/png"
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _data_url_to_bytes(value: str) -> tuple[bytes, str]:
    """Decode a base64 data URL into bytes and MIME type."""
    if not value.startswith("data:") or ";base64," not in value:
        raise ValueError("Expected a base64 data URL.")
    header, encoded = value.split(";base64,", 1)
    mime_type = header[5:] or "image/png"
    return base64.b64decode(encoded), mime_type


def _image_ref_to_url(image: Any) -> str:
    """Convert a path, URL, data URL, or attachment-like dict to image_url.url."""
    if isinstance(image, dict):
        for key in ("data_url", "dataUrl", "path", "url"):
            value = image.get(key)
            if value:
                return _image_ref_to_url(value)
        content = image.get("content")
        mime_type = image.get("mime_type") or image.get("mimeType") or "image/png"
        if isinstance(content, bytes):
            encoded = base64.b64encode(content).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        if isinstance(content, str) and content.startswith("data:image/"):
            return content
        raise ValueError("Image dict must include path, url, data_url, or image bytes content.")

    if not isinstance(image, str):
        raise TypeError(f"Unsupported image reference type: {type(image).__name__}")

    value = image.strip()
    if value.startswith(("data:image/", "http://", "https://")):
        return value
    return _path_to_data_url(value)


def _image_ref_to_bytes(image: Any, timeout: float = 30.0) -> tuple[bytes, str]:
    """Convert a path, URL, data URL, or attachment-like dict to image bytes."""
    if isinstance(image, dict):
        for key in ("data_url", "dataUrl", "path", "url"):
            value = image.get(key)
            if value:
                return _image_ref_to_bytes(value, timeout=timeout)
        content = image.get("content")
        mime_type = image.get("mime_type") or image.get("mimeType") or "image/png"
        if isinstance(content, bytes):
            return content, str(mime_type)
        if isinstance(content, str) and content.startswith("data:image/"):
            return _data_url_to_bytes(content)
        raise ValueError("Image dict must include path, url, data_url, or image bytes content.")

    if not isinstance(image, str):
        raise TypeError(f"Unsupported image reference type: {type(image).__name__}")

    value = image.strip()
    if value.startswith("data:image/"):
        return _data_url_to_bytes(value)

    if value.startswith(("http://", "https://")):
        try:
            import requests
        except ImportError:
            raise ImportError(
                "requests is required to fetch remote Gemini VLM images. "
                "Install with: pip install requests"
            ) from None
        response = requests.get(value, timeout=timeout)
        response.raise_for_status()
        mime_type = response.headers.get("content-type") or mimetypes.guess_type(value)[0]
        return response.content, mime_type or "image/png"

    p = Path(value).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Image file not found: {p}")
    mime_type = mimetypes.guess_type(p.name)[0] or "image/png"
    return p.read_bytes(), mime_type


class GemmaVLMProvider(VLMProvider):
    """Gemma vision provider backed by a local OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "gemma4:e4b",
        timeout: float = 120.0,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **_: Any,
    ):
        self.base_url = (
            base_url
            or os.getenv("GEMMA_VLM_BASE_URL")
            or os.getenv("OPENBENCH_VLM_BASE_URL")
            or "http://localhost:11434/v1"
        )
        self.api_key = (
            api_key
            or os.getenv("GEMMA_VLM_API_KEY")
            or os.getenv("OPENBENCH_VLM_API_KEY")
        )
        self.model = model
        self.timeout = float(timeout)
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def provider_name(self) -> str:
        return "ollama"

    def generate(
        self,
        prompt: str,
        images: list[Any],
        model: str = "",
        **params,
    ) -> LLMResponse:
        """Generate a text response from one or more images."""
        if not images:
            raise ValueError("GemmaVLMProvider requires at least one image.")

        try:
            import requests
        except ImportError:
            raise ImportError(
                "requests is required for GemmaVLMProvider. Install with: pip install requests"
            ) from None

        resolved_model = model or params.pop("model", None) or self.model
        temperature = params.pop("temperature", self.temperature)
        max_tokens = params.pop("max_tokens", params.pop("max_output_tokens", self.max_tokens))

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_ref_to_url(image)},
                }
            )

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(params)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        endpoint = _normalize_chat_completions_url(self.base_url)
        logger.info(
            "[vision] provider=ollama resolved_model=%s endpoint=%s images=%d",
            resolved_model,
            endpoint,
            len(images),
        )
        response = requests.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
        try:
            response.raise_for_status()
        except Exception as exc:
            body = getattr(response, "text", "")
            detail = f": {body[:1000]}" if body else ""
            raise RuntimeError(
                f"VLM request failed at {endpoint} with status "
                f"{getattr(response, 'status_code', 'unknown')}{detail}"
            ) from exc

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or choice.get("text") or ""
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)

        return LLMResponse(
            text=str(text),
            model=str(data.get("model") or resolved_model),
            tokens_used=total_tokens,
            cost=0.0,
            metadata={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "provider": self.provider_name,
                "image_count": len(images),
            },
        )


class GeminiVLMProvider(VLMProvider):
    """Gemini vision provider using the google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        timeout: float = 120.0,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        **_: Any,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = model
        self.timeout = float(timeout)
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
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
                    "google-genai package required for GeminiVLMProvider. "
                    "Install with: pip install google-genai"
                ) from None

            if not self.api_key:
                raise ValueError(
                    "Google API key required. Set GOOGLE_API_KEY or GEMINI_API_KEY, "
                    "or pass api_key to GeminiVLMProvider."
                )

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(
        self,
        prompt: str,
        images: list[Any],
        model: str = "",
        **params,
    ) -> LLMResponse:
        """Generate a text response from one or more images with Gemini."""
        if not images:
            raise ValueError("GeminiVLMProvider requires at least one image.")

        from google.genai import types

        client = self._get_client()
        resolved_model = model or params.pop("model", None) or self.model
        temperature = params.pop("temperature", self.temperature)
        max_output_tokens = params.pop(
            "max_tokens",
            params.pop("max_output_tokens", self.max_output_tokens),
        )

        parts = [types.Part.from_text(text=prompt)]
        for image in images:
            image_bytes, mime_type = _image_ref_to_bytes(image, timeout=self.timeout)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        response = client.models.generate_content(
            model=resolved_model,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        total_tokens = int(
            getattr(usage, "total_token_count", 0) or prompt_tokens + completion_tokens
        )

        return LLMResponse(
            text=str(getattr(response, "text", "") or ""),
            model=resolved_model,
            tokens_used=total_tokens,
            cost=0.0,
            metadata={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "provider": self.provider_name,
                "image_count": len(images),
            },
        )


from openbench.core.registry import VLMProviderRegistry  # noqa: E402

VLMProviderRegistry.register(
    "vision",
    "gemma",
    description="Local Gemma VLM provider via OpenAI-compatible chat completions",
)(GemmaVLMProvider)

VLMProviderRegistry.register(
    "vision",
    "ollama",
    description="Local Ollama VLM provider via OpenAI-compatible chat completions",
)(GemmaVLMProvider)

VLMProviderRegistry.register(
    "vision",
    "gemini",
    description="Gemini vision provider via google-genai",
)(GeminiVLMProvider)
