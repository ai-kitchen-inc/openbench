"""LangExtract data source - structured entity extraction from text.

Uses Google's LangExtract library to extract structured information
from unstructured text based on user-defined instructions and few-shot examples.

Supported providers:
- gemini: Google Gemini models (default)
- openai: OpenAI GPT models
- ollama: Local Ollama models

Example:
    # Basic extraction
    source = LangExtractSource(
        text="John Smith, 45, diagnosed with Type 2 Diabetes on 2024-01-15.",
        prompt="Extract patients and diagnoses",
        examples=[{
            "text": "Jane Doe, 30, has hypertension",
            "extractions": [
                {"class": "patient", "text": "Jane Doe", "attributes": {"age": "30"}},
                {"class": "diagnosis", "text": "hypertension"},
            ]
        }]
    )
    result = source.extract()

    # In workflow with PDFSource
    workflow = PDFSource("report.pdf") | LangExtractSource(
        prompt="Extract entities",
        examples=[...]
    )
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from openbench.core.abstractions import DataSource, RawData
from openbench.data.exceptions import ExtractionError, ValidationError

if TYPE_CHECKING:
    from openbench.core.abstractions import DataStore

LangExtractProvider = Literal["gemini", "openai", "ollama"]


class LangExtractSource(DataSource):
    """Data source for structured entity extraction using LangExtract.

    Uses LLMs to extract structured information from unstructured text
    based on user-defined instructions and few-shot examples. Every extraction
    is mapped to its exact location in the source text (source grounding).

    Providers:
        - gemini: Google Gemini models (default, recommended)
        - openai: OpenAI GPT models
        - ollama: Local Ollama models (no API key needed)

    Example:
        # Basic extraction
        source = LangExtractSource(
            text="Romeo spoke with passion about Juliet.",
            prompt="Extract characters and emotions",
            examples=[{
                "text": "Hamlet pondered deeply",
                "extractions": [
                    {"class": "character", "text": "Hamlet"},
                    {"class": "emotion", "text": "pondered deeply",
                     "attributes": {"feeling": "contemplation"}},
                ]
            }]
        )
        result = source.extract()
        print(result.content["summary"])

        # In workflow
        workflow = PDFSource("doc.pdf") | LangExtractSource(
            prompt="Extract entities", examples=[...]
        )
    """

    ENV_KEYS: dict[str, list[str]] = {
        "gemini": ["GOOGLE_API_KEY", "LANGEXTRACT_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "ollama": [],
    }

    DEFAULT_MODELS: dict[str, str] = {
        "gemini": "gemini-2.5-flash",
        "openai": "gpt-4o",
        "ollama": "gemma2:2b",
    }

    def __init__(
        self,
        prompt: str,
        text: str | None = None,
        url: str | None = None,
        examples: list[dict[str, Any]] | None = None,
        provider: LangExtractProvider = "gemini",
        model: str | None = None,
        api_key: str | None = None,
        model_url: str = "http://localhost:11434",
        extraction_passes: int = 1,
        max_workers: int = 10,
        max_char_buffer: int = 2000,
        temperature: float = 0.3,
        include_positions: bool = True,
        filter_classes: list[str] | None = None,
        store: DataStore | None = None,
        auto_index: bool = False,
    ):
        """Initialize LangExtract source.

        Args:
            prompt: Extraction instructions describing what to extract.
            text: Input text to extract from. Can also be provided via invoke().
            url: URL to document. Alternative to text.
            examples: Few-shot examples in OpenBench dict format. Each dict has
                'text' (str) and 'extractions' (list of dicts with 'class', 'text',
                and optional 'attributes').
            provider: LLM provider (default: "gemini").
            model: Model ID (uses provider default if not specified).
            api_key: API key (reads from env if not provided).
            model_url: Ollama server URL (default: "http://localhost:11434").
            extraction_passes: Number of extraction passes for better recall (default: 1).
            max_workers: Parallel workers for long documents (default: 10).
            max_char_buffer: Chunk size for long documents (default: 2000).
            temperature: Generation temperature (default: 0.3).
            include_positions: Include character positions in output (default: True).
            filter_classes: Only return extractions of these classes (default: all).
            store: Optional DataStore for auto-indexing extracted content.
            auto_index: Automatically index to store on extract (default: False).
        """
        self.prompt = prompt
        self.text = text
        self.url = url
        self.examples = examples or []
        self.provider = provider
        self.model = model or self.DEFAULT_MODELS.get(provider)
        self.model_url = model_url
        self.extraction_passes = extraction_passes
        self.max_workers = max_workers
        self.max_char_buffer = max_char_buffer
        self.temperature = temperature
        self.include_positions = include_positions
        self.filter_classes = filter_classes
        self.store = store
        self.auto_index = auto_index

        self.api_key = api_key or self._get_api_key()
        self._last_lx_result = None

    def _get_api_key(self) -> str | None:
        """Get API key from environment variables."""
        for key_name in self.ENV_KEYS.get(self.provider, []):
            if key := os.getenv(key_name):
                return key
        return None

    @property
    def source_type(self) -> str:
        """Return source type identifier."""
        return "langextract"

    @property
    def source_id(self) -> str:
        """Return unique identifier based on prompt and input."""
        content = f"{self.prompt}:{(self.text or self.url or '')[:100]}"
        hash_suffix = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"langextract_{self.provider}_{hash_suffix}"

    def validate(self) -> bool:
        """Validate source configuration.

        Returns:
            True if configuration is valid.

        Raises:
            ValidationError: If configuration is invalid.
        """
        if not self.prompt or not self.prompt.strip():
            raise ValidationError("Prompt cannot be empty")

        if self.provider not in self.ENV_KEYS:
            raise ValidationError(
                f"Unsupported provider: {self.provider}. Available: {list(self.ENV_KEYS.keys())}"
            )

        if self.provider != "ollama" and not self.api_key:
            env_vars = self.ENV_KEYS.get(self.provider, [])
            raise ValidationError(
                f"API key required for {self.provider}. "
                f"Set via api_key or env: {', '.join(env_vars)}"
            )

        return True

    def get_metadata(self) -> dict[str, Any]:
        """Get metadata about the extraction source.

        Returns:
            Dict with extraction configuration details.
        """
        return {
            "prompt": self.prompt,
            "provider": self.provider,
            "model": self.model,
            "extraction_passes": self.extraction_passes,
            "max_workers": self.max_workers,
            "temperature": self.temperature,
            "has_examples": len(self.examples) > 0,
            "example_count": len(self.examples),
        }

    def _convert_examples(self, examples: list[dict[str, Any]]) -> list:
        """Convert OpenBench examples to LangExtract ExampleData format.

        Args:
            examples: List of dicts with 'text' and 'extractions' keys.
                Each extraction has 'class', 'text', and optional 'attributes'.
                Attribute values must be str or list[str] per LangExtract API.

        Returns:
            List of lx.data.ExampleData objects.
        """
        import langextract as lx

        converted = []
        for ex in examples:
            extractions = [
                lx.data.Extraction(
                    extraction_class=e["class"],
                    extraction_text=e["text"],
                    attributes=self._coerce_attributes(e.get("attributes")),
                )
                for e in ex.get("extractions", [])
            ]
            converted.append(lx.data.ExampleData(text=ex["text"], extractions=extractions))
        return converted

    @staticmethod
    def _coerce_attributes(
        attrs: dict[str, Any] | None,
    ) -> dict[str, str] | None:
        """Coerce attribute values to str as required by LangExtract API."""
        if not attrs:
            return None
        return {k: str(v) if not isinstance(v, str | list) else v for k, v in attrs.items()}

    def _build_extract_params(self) -> dict[str, Any]:
        """Build parameters dict for lx.extract().

        Returns:
            Dict of keyword arguments for langextract.extract().
        """
        params: dict[str, Any] = {
            "text_or_documents": self.url or self.text,
            "prompt_description": self.prompt,
            "model_id": self.model,
            "extraction_passes": self.extraction_passes,
            "max_workers": self.max_workers,
            "max_char_buffer": self.max_char_buffer,
            "temperature": self.temperature,
            "show_progress": False,
        }

        if self.examples:
            params["examples"] = self._convert_examples(self.examples)

        if self.provider == "gemini":
            params["api_key"] = self.api_key

        elif self.provider == "openai":
            params["api_key"] = self.api_key
            params["fence_output"] = True
            params["use_schema_constraints"] = False

        elif self.provider == "ollama":
            params["model_url"] = self.model_url

        return params

    def _result_to_raw_data(self, result: Any) -> RawData:
        """Convert LangExtract result to RawData.

        Args:
            result: LangExtract extraction result object.

        Returns:
            RawData with structured extraction content.
        """
        extractions = []
        for e in result.extractions:
            extraction_dict: dict[str, Any] = {
                "class": e.extraction_class,
                "text": e.extraction_text,
                "attributes": e.attributes or {},
            }

            if self.include_positions and hasattr(e, "char_interval"):
                interval = e.char_interval
                if interval is None:
                    extraction_dict["position"] = {"start": None, "end": None}
                elif hasattr(interval, "start_pos"):
                    extraction_dict["position"] = {
                        "start": interval.start_pos,
                        "end": interval.end_pos,
                    }
                else:
                    extraction_dict["position"] = {
                        "start": interval[0],
                        "end": interval[1],
                    }

            extractions.append(extraction_dict)

        if self.filter_classes:
            extractions = [e for e in extractions if e["class"] in self.filter_classes]

        by_class: dict[str, list[dict[str, Any]]] = {}
        for e in extractions:
            cls = e["class"]
            if cls not in by_class:
                by_class[cls] = []
            by_class[cls].append(e)

        content = {
            "extractions": extractions,
            "by_class": by_class,
            "summary": {
                "total": len(extractions),
                "classes": {cls: len(items) for cls, items in by_class.items()},
            },
        }

        metadata = {
            **self.get_metadata(),
            "extraction_count": len(extractions),
            "classes_found": list(by_class.keys()),
            "source_text_length": len(result.text) if hasattr(result, "text") else None,
            "extracted_at": datetime.now().isoformat(),
        }

        raw_data = RawData(
            content=content,
            content_type="structured",
            metadata=metadata,
            source=self,
        )

        if self.store and self.auto_index:
            try:
                self.store.index(raw_data)
            except Exception as e:
                import warnings

                warnings.warn(f"Failed to index to store: {e}", stacklevel=2)

        return raw_data

    def extract(self) -> RawData:
        """Execute entity extraction and return structured results.

        Returns:
            RawData with extractions as structured content. The content dict
            contains 'extractions' (list), 'by_class' (grouped dict), and
            'summary' (counts).

        Raises:
            ExtractionError: If extraction fails.
            ValidationError: If configuration is invalid.
        """
        if not self.text and not self.url:
            raise ValidationError(
                "No input provided. Set text, url, or use in workflow chain via invoke()."
            )

        self.validate()

        try:
            import langextract as lx
        except ImportError:
            raise ExtractionError(
                "langextract is required for entity extraction. "
                "Install with: pip install langextract"
            ) from None

        params = self._build_extract_params()

        try:
            result = lx.extract(**params)
        except Exception as e:
            raise ExtractionError(f"LangExtract extraction failed: {e}") from e

        self._last_lx_result = result
        return self._result_to_raw_data(result)

    def invoke(self, input: Any = None, config: Any | None = None) -> RawData:
        """Chainable invoke for workflow composition.

        Accepts input from previous step in chain (e.g., PDFSource).

        Args:
            input: Can be str (text), RawData, or dict with 'text'/'content' key.
            config: Optional dict with extraction config overrides.

        Returns:
            RawData with extraction results.
        """
        if isinstance(input, str):
            self.text = input
        elif isinstance(input, RawData):
            if isinstance(input.content, str):
                self.text = input.content
            elif isinstance(input.content, dict):
                self.text = input.content.get("text", str(input.content))
            else:
                self.text = str(input.content)
        elif isinstance(input, dict):
            if "text" in input:
                self.text = input["text"]
            elif "content" in input:
                self.text = input["content"]
            if "prompt" in input:
                self.prompt = input["prompt"]

        if config and isinstance(config, dict):
            for key in ("extraction_passes", "max_workers", "filter_classes"):
                if key in config:
                    setattr(self, key, config[key])

        return self.extract()

    def visualize(
        self,
        output_path: str | None = None,
        max_text_display: int = 400,
    ) -> str:
        """Generate HTML visualization of extraction results.

        Must call extract() first to have results available.

        Args:
            output_path: Path to save HTML file. If None, returns HTML string.
            max_text_display: Max characters to display per document.

        Returns:
            HTML string, or file path if output_path is provided.

        Raises:
            ExtractionError: If langextract not installed or no results available.
        """
        try:
            import langextract as lx
        except ImportError:
            raise ExtractionError(
                "langextract is required for visualization. Install with: pip install langextract"
            ) from None

        if self._last_lx_result is None:
            raise ExtractionError("No extraction result available. Call extract() first.")

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            temp_path = f.name

        try:
            lx.io.save_annotated_documents(
                annotated_documents=[self._last_lx_result],
                output_name=temp_path,
            )

            html_content = lx.visualize(
                data=temp_path,
                max_text_display=max_text_display,
                skip_empty=True,
            )

            html_str = html_content.data if hasattr(html_content, "data") else str(html_content)
        finally:
            os.unlink(temp_path)

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_str)
            return output_path

        return html_str

    async def aextract(self) -> RawData:
        """Async version of extract (runs sync extraction in executor)."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.extract)
