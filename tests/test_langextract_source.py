"""Tests for LangExtractSource."""

import unittest
from unittest.mock import MagicMock, patch

from openbench.data.sources.langextract import LangExtractSource
from openbench.core.abstractions import RawData
from openbench.data.exceptions import ExtractionError, ValidationError


class TestLangExtractSourceInit(unittest.TestCase):
    """Tests for LangExtractSource initialization."""

    def test_init_with_text(self):
        source = LangExtractSource(prompt="Extract entities", text="Hello world")
        self.assertEqual(source.text, "Hello world")
        self.assertEqual(source.prompt, "Extract entities")

    def test_init_with_url(self):
        source = LangExtractSource(prompt="Extract", url="https://example.com/doc.txt")
        self.assertEqual(source.url, "https://example.com/doc.txt")

    def test_init_default_provider(self):
        source = LangExtractSource(prompt="Extract")
        self.assertEqual(source.provider, "gemini")

    def test_init_default_model_gemini(self):
        source = LangExtractSource(prompt="Extract", provider="gemini")
        self.assertEqual(source.model, "gemini-2.5-flash")

    def test_init_default_model_openai(self):
        source = LangExtractSource(prompt="Extract", provider="openai")
        self.assertEqual(source.model, "gpt-4o")

    def test_init_default_model_ollama(self):
        source = LangExtractSource(prompt="Extract", provider="ollama")
        self.assertEqual(source.model, "gemma2:2b")

    def test_init_custom_model(self):
        source = LangExtractSource(prompt="Extract", model="gemini-2.5-pro")
        self.assertEqual(source.model, "gemini-2.5-pro")

    def test_init_with_examples(self):
        examples = [
            {
                "text": "Romeo spoke",
                "extractions": [{"class": "character", "text": "Romeo"}],
            }
        ]
        source = LangExtractSource(prompt="Extract", examples=examples)
        self.assertEqual(len(source.examples), 1)

    def test_init_default_examples_empty(self):
        source = LangExtractSource(prompt="Extract")
        self.assertEqual(source.examples, [])

    def test_init_extraction_config(self):
        source = LangExtractSource(
            prompt="Extract",
            extraction_passes=3,
            max_workers=20,
            max_char_buffer=1000,
            temperature=0.5,
        )
        self.assertEqual(source.extraction_passes, 3)
        self.assertEqual(source.max_workers, 20)
        self.assertEqual(source.max_char_buffer, 1000)
        self.assertEqual(source.temperature, 0.5)

    def test_init_ollama_model_url(self):
        source = LangExtractSource(
            prompt="Extract",
            provider="ollama",
            model_url="http://my-server:11434",
        )
        self.assertEqual(source.model_url, "http://my-server:11434")


class TestLangExtractSourceProperties(unittest.TestCase):
    """Tests for LangExtractSource properties."""

    def test_source_type(self):
        source = LangExtractSource(prompt="Extract")
        self.assertEqual(source.source_type, "langextract")

    def test_source_id_format(self):
        source = LangExtractSource(prompt="Extract", provider="gemini")
        self.assertTrue(source.source_id.startswith("langextract_gemini_"))

    def test_source_id_unique(self):
        source1 = LangExtractSource(prompt="Extract characters", text="text one")
        source2 = LangExtractSource(prompt="Extract emotions", text="text two")
        self.assertNotEqual(source1.source_id, source2.source_id)

    def test_source_id_with_url(self):
        source = LangExtractSource(prompt="Extract", url="https://example.com")
        self.assertIn("langextract_gemini_", source.source_id)


class TestLangExtractSourceValidation(unittest.TestCase):
    """Tests for LangExtractSource validation."""

    def test_validate_empty_prompt(self):
        source = LangExtractSource(prompt="")
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_whitespace_prompt(self):
        source = LangExtractSource(prompt="   ")
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_unsupported_provider(self):
        source = LangExtractSource(prompt="Extract")
        source.provider = "invalid"
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_missing_api_key_gemini(self):
        source = LangExtractSource(prompt="Extract", provider="gemini")
        source.api_key = None
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_missing_api_key_openai(self):
        source = LangExtractSource(prompt="Extract", provider="openai")
        source.api_key = None
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_ollama_no_api_key_required(self):
        source = LangExtractSource(prompt="Extract", provider="ollama")
        source.api_key = None
        self.assertTrue(source.validate())

    def test_validate_success(self):
        source = LangExtractSource(prompt="Extract", provider="gemini", api_key="test")
        self.assertTrue(source.validate())


class TestLangExtractSourceMetadata(unittest.TestCase):
    """Tests for LangExtractSource metadata."""

    def test_get_metadata_fields(self):
        source = LangExtractSource(
            prompt="Extract entities",
            provider="gemini",
            temperature=0.5,
            extraction_passes=3,
        )
        metadata = source.get_metadata()

        self.assertEqual(metadata["prompt"], "Extract entities")
        self.assertEqual(metadata["provider"], "gemini")
        self.assertEqual(metadata["temperature"], 0.5)
        self.assertEqual(metadata["extraction_passes"], 3)

    def test_get_metadata_with_examples(self):
        examples = [{"text": "test", "extractions": []}]
        source = LangExtractSource(prompt="Extract", examples=examples)
        metadata = source.get_metadata()

        self.assertTrue(metadata["has_examples"])
        self.assertEqual(metadata["example_count"], 1)

    def test_get_metadata_without_examples(self):
        source = LangExtractSource(prompt="Extract")
        metadata = source.get_metadata()

        self.assertFalse(metadata["has_examples"])
        self.assertEqual(metadata["example_count"], 0)


class TestLangExtractSourceExamples(unittest.TestCase):
    """Tests for examples conversion."""

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_convert_examples_basic(self, mock_key):
        mock_key.return_value = "test"

        mock_lx = MagicMock()
        mock_extraction = MagicMock()
        mock_example = MagicMock()
        mock_lx.data.Extraction.return_value = mock_extraction
        mock_lx.data.ExampleData.return_value = mock_example

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(prompt="Extract")
            examples = [
                {
                    "text": "Romeo spoke",
                    "extractions": [
                        {"class": "character", "text": "Romeo", "attributes": {"role": "lead"}}
                    ],
                }
            ]
            result = source._convert_examples(examples)

            mock_lx.data.Extraction.assert_called_once_with(
                extraction_class="character",
                extraction_text="Romeo",
                attributes={"role": "lead"},
            )
            mock_lx.data.ExampleData.assert_called_once()
            self.assertEqual(len(result), 1)

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_convert_examples_without_attributes(self, mock_key):
        mock_key.return_value = "test"

        mock_lx = MagicMock()
        mock_lx.data.Extraction.return_value = MagicMock()
        mock_lx.data.ExampleData.return_value = MagicMock()

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(prompt="Extract")
            examples = [
                {
                    "text": "test",
                    "extractions": [{"class": "entity", "text": "test"}],
                }
            ]
            source._convert_examples(examples)

            mock_lx.data.Extraction.assert_called_once_with(
                extraction_class="entity",
                extraction_text="test",
                attributes=None,
            )

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_convert_examples_empty_list(self, mock_key):
        mock_key.return_value = "test"

        mock_lx = MagicMock()
        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(prompt="Extract")
            result = source._convert_examples([])
            self.assertEqual(result, [])


class TestLangExtractSourceExtract(unittest.TestCase):
    """Tests for LangExtractSource extraction."""

    def test_extract_no_input_raises_validation_error(self):
        source = LangExtractSource(prompt="Extract", api_key="test")
        with self.assertRaises(ValidationError) as ctx:
            source.extract()
        self.assertIn("No input provided", str(ctx.exception))

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_missing_langextract(self, mock_key):
        mock_key.return_value = "test"

        source = LangExtractSource(prompt="Extract", text="Hello", api_key="test")

        with patch.dict("sys.modules", {"langextract": None}):
            with self.assertRaises(ExtractionError) as ctx:
                source.extract()
            self.assertIn("langextract is required", str(ctx.exception))

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_returns_raw_data(self, mock_key):
        mock_key.return_value = "test"

        mock_extraction = MagicMock()
        mock_extraction.extraction_class = "character"
        mock_extraction.extraction_text = "Romeo"
        mock_extraction.attributes = {"role": "protagonist"}
        mock_extraction.char_interval = (0, 5)

        mock_result = MagicMock()
        mock_result.extractions = [mock_extraction]
        mock_result.text = "Romeo spoke with passion"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result
        mock_lx.data.Extraction = MagicMock
        mock_lx.data.ExampleData = MagicMock

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract characters",
                text="Romeo spoke with passion",
                provider="gemini",
                api_key="test-key",
            )
            result = source.extract()

            self.assertIsInstance(result, RawData)
            self.assertEqual(result.content_type, "structured")
            self.assertEqual(len(result.content["extractions"]), 1)
            self.assertEqual(result.content["extractions"][0]["class"], "character")
            self.assertEqual(result.content["extractions"][0]["text"], "Romeo")

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_content_structure(self, mock_key):
        mock_key.return_value = "test"

        mock_e1 = MagicMock()
        mock_e1.extraction_class = "character"
        mock_e1.extraction_text = "Romeo"
        mock_e1.attributes = {}
        mock_e1.char_interval = (0, 5)

        mock_e2 = MagicMock()
        mock_e2.extraction_class = "emotion"
        mock_e2.extraction_text = "passion"
        mock_e2.attributes = {"feeling": "love"}
        mock_e2.char_interval = (20, 27)

        mock_result = MagicMock()
        mock_result.extractions = [mock_e1, mock_e2]
        mock_result.text = "Romeo spoke with passion"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract", text="Romeo spoke with passion", api_key="test"
            )
            result = source.extract()

            self.assertIn("extractions", result.content)
            self.assertIn("by_class", result.content)
            self.assertIn("summary", result.content)
            self.assertEqual(result.content["summary"]["total"], 2)
            self.assertEqual(result.content["summary"]["classes"]["character"], 1)
            self.assertEqual(result.content["summary"]["classes"]["emotion"], 1)

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_with_filter_classes(self, mock_key):
        mock_key.return_value = "test"

        mock_e1 = MagicMock()
        mock_e1.extraction_class = "character"
        mock_e1.extraction_text = "Romeo"
        mock_e1.attributes = {}
        mock_e1.char_interval = None

        mock_e2 = MagicMock()
        mock_e2.extraction_class = "emotion"
        mock_e2.extraction_text = "passion"
        mock_e2.attributes = {}
        mock_e2.char_interval = None

        mock_result = MagicMock()
        mock_result.extractions = [mock_e1, mock_e2]
        mock_result.text = "text"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract",
                text="text",
                api_key="test",
                filter_classes=["character"],
            )
            result = source.extract()

            self.assertEqual(len(result.content["extractions"]), 1)
            self.assertEqual(result.content["extractions"][0]["class"], "character")

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_with_positions(self, mock_key):
        mock_key.return_value = "test"

        mock_extraction = MagicMock()
        mock_extraction.extraction_class = "entity"
        mock_extraction.extraction_text = "Romeo"
        mock_extraction.attributes = {}
        mock_extraction.char_interval = (10, 15)

        mock_result = MagicMock()
        mock_result.extractions = [mock_extraction]
        mock_result.text = "text"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract", text="text", api_key="test", include_positions=True
            )
            result = source.extract()

            extraction = result.content["extractions"][0]
            self.assertIn("position", extraction)
            self.assertEqual(extraction["position"]["start"], 10)
            self.assertEqual(extraction["position"]["end"], 15)

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_error_handling(self, mock_key):
        mock_key.return_value = "test"

        mock_lx = MagicMock()
        mock_lx.extract.side_effect = Exception("API Error")

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract", text="text", provider="gemini", api_key="test"
            )
            with self.assertRaises(ExtractionError) as ctx:
                source.extract()
            self.assertIn("LangExtract extraction failed", str(ctx.exception))

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_metadata(self, mock_key):
        mock_key.return_value = "test"

        mock_result = MagicMock()
        mock_result.extractions = []
        mock_result.text = "Hello world"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract", text="Hello world", api_key="test"
            )
            result = source.extract()

            self.assertIn("extraction_count", result.metadata)
            self.assertIn("classes_found", result.metadata)
            self.assertIn("extracted_at", result.metadata)
            self.assertEqual(result.metadata["extraction_count"], 0)


class TestLangExtractSourceChainable(unittest.TestCase):
    """Tests for LangExtractSource chainable interface."""

    @patch.object(LangExtractSource, "extract")
    def test_invoke_calls_extract(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = LangExtractSource(prompt="Extract", text="text", api_key="test")
        source.invoke()

        mock_extract.assert_called_once()

    @patch.object(LangExtractSource, "extract")
    def test_invoke_with_string(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = LangExtractSource(prompt="Extract", api_key="test")
        source.invoke("new text input")

        self.assertEqual(source.text, "new text input")

    @patch.object(LangExtractSource, "extract")
    def test_invoke_with_raw_data_string_content(self, mock_extract):
        mock_extract.return_value = MagicMock()

        raw_data = RawData(
            content="PDF text content",
            content_type="text",
            metadata={},
        )

        source = LangExtractSource(prompt="Extract", api_key="test")
        source.invoke(raw_data)

        self.assertEqual(source.text, "PDF text content")

    @patch.object(LangExtractSource, "extract")
    def test_invoke_with_raw_data_dict_content(self, mock_extract):
        mock_extract.return_value = MagicMock()

        raw_data = RawData(
            content={"text": "Some text", "other": "data"},
            content_type="structured",
            metadata={},
        )

        source = LangExtractSource(prompt="Extract", api_key="test")
        source.invoke(raw_data)

        self.assertEqual(source.text, "Some text")

    @patch.object(LangExtractSource, "extract")
    def test_invoke_with_dict(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = LangExtractSource(prompt="Extract", api_key="test")
        source.invoke({"text": "dict text", "prompt": "New prompt"})

        self.assertEqual(source.text, "dict text")
        self.assertEqual(source.prompt, "New prompt")

    @patch.object(LangExtractSource, "extract")
    def test_invoke_with_dict_content_key(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = LangExtractSource(prompt="Extract", api_key="test")
        source.invoke({"content": "content text"})

        self.assertEqual(source.text, "content text")

    @patch.object(LangExtractSource, "extract")
    def test_invoke_with_config_overrides(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = LangExtractSource(
            prompt="Extract", text="text", api_key="test", extraction_passes=1
        )
        source.invoke(config={"extraction_passes": 5, "max_workers": 30})

        self.assertEqual(source.extraction_passes, 5)
        self.assertEqual(source.max_workers, 30)


class TestLangExtractSourceProviders(unittest.TestCase):
    """Tests for LangExtractSource provider configurations."""

    def test_all_providers_in_env_keys(self):
        providers = ["gemini", "openai", "ollama"]
        for provider in providers:
            self.assertIn(provider, LangExtractSource.ENV_KEYS)

    def test_all_providers_have_default_models(self):
        providers = ["gemini", "openai", "ollama"]
        for provider in providers:
            self.assertIn(provider, LangExtractSource.DEFAULT_MODELS)

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_get_api_key_gemini(self):
        source = LangExtractSource(prompt="Extract", provider="gemini")
        self.assertEqual(source.api_key, "test-key")

    @patch.dict("os.environ", {"LANGEXTRACT_API_KEY": "lx-key"})
    def test_get_api_key_langextract_fallback(self):
        source = LangExtractSource(prompt="Extract", provider="gemini")
        self.assertEqual(source.api_key, "lx-key")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key"})
    def test_get_api_key_openai(self):
        source = LangExtractSource(prompt="Extract", provider="openai")
        self.assertEqual(source.api_key, "openai-key")

    def test_ollama_no_api_key(self):
        source = LangExtractSource(prompt="Extract", provider="ollama")
        # Ollama has empty ENV_KEYS, so api_key should be None
        self.assertIsNone(source.api_key)

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_build_params_gemini(self, mock_key):
        mock_key.return_value = "test-key"

        mock_lx = MagicMock()
        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract", text="text", provider="gemini", api_key="test-key"
            )
            params = source._build_extract_params()

            self.assertEqual(params["api_key"], "test-key")
            self.assertEqual(params["model_id"], "gemini-2.5-flash")
            self.assertNotIn("fence_output", params)

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_build_params_openai(self, mock_key):
        mock_key.return_value = "test-key"

        mock_lx = MagicMock()
        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract", text="text", provider="openai", api_key="test-key"
            )
            params = source._build_extract_params()

            self.assertEqual(params["api_key"], "test-key")
            self.assertTrue(params["fence_output"])
            self.assertFalse(params["use_schema_constraints"])

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_build_params_ollama(self, mock_key):
        mock_key.return_value = None

        mock_lx = MagicMock()
        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract",
                text="text",
                provider="ollama",
                model_url="http://localhost:11434",
            )
            params = source._build_extract_params()

            self.assertEqual(params["model_url"], "http://localhost:11434")
            self.assertEqual(params["model_id"], "gemma2:2b")
            self.assertNotIn("api_key", params)


class TestLangExtractSourceAutoIndex(unittest.TestCase):
    """Tests for auto-indexing to DataStore."""

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_with_auto_index(self, mock_key):
        mock_key.return_value = "test"

        mock_store = MagicMock()

        mock_result = MagicMock()
        mock_result.extractions = []
        mock_result.text = "test"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract",
                text="test",
                api_key="test",
                store=mock_store,
                auto_index=True,
            )
            source.extract()

            mock_store.index.assert_called_once()

    @patch("openbench.data.sources.langextract.LangExtractSource._get_api_key")
    def test_extract_auto_index_failure_warns(self, mock_key):
        mock_key.return_value = "test"

        mock_store = MagicMock()
        mock_store.index.side_effect = Exception("Store error")

        mock_result = MagicMock()
        mock_result.extractions = []
        mock_result.text = "test"

        mock_lx = MagicMock()
        mock_lx.extract.return_value = mock_result

        with patch.dict("sys.modules", {"langextract": mock_lx}):
            source = LangExtractSource(
                prompt="Extract",
                text="test",
                api_key="test",
                store=mock_store,
                auto_index=True,
            )
            # Should not raise, just warn
            import warnings

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = source.extract()
                self.assertEqual(len(w), 1)
                self.assertIn("Failed to index", str(w[0].message))

            self.assertIsInstance(result, RawData)


if __name__ == "__main__":
    unittest.main()
