"""Tests for GroundedSearchSource."""

import unittest
from unittest.mock import MagicMock, patch

from openbench.data.exceptions import ExtractionError, ValidationError
from openbench.data.sources.grounded_search import GroundedSearchSource


class TestGroundedSearchSourceInit(unittest.TestCase):
    """Tests for GroundedSearchSource initialization."""

    def test_init_with_query(self):
        source = GroundedSearchSource(query="test query")
        self.assertEqual(source.query, "test query")

    def test_init_default_provider(self):
        source = GroundedSearchSource(query="test")
        self.assertEqual(source.provider, "gemini")

    def test_init_default_model_gemini(self):
        source = GroundedSearchSource(query="test", provider="gemini")
        self.assertEqual(source.model, "gemini-2.5-flash")

    def test_init_default_model_perplexity(self):
        source = GroundedSearchSource(query="test", provider="perplexity")
        self.assertEqual(source.model, "llama-3.1-sonar-small-128k-online")

    def test_init_custom_model(self):
        source = GroundedSearchSource(query="test", model="gemini-2.5-pro")
        self.assertEqual(source.model, "gemini-2.5-pro")


class TestGroundedSearchSourceProperties(unittest.TestCase):
    """Tests for GroundedSearchSource properties."""

    def test_source_type(self):
        source = GroundedSearchSource(query="test")
        self.assertEqual(source.source_type, "grounded_search")

    def test_source_id_format(self):
        source = GroundedSearchSource(query="test", provider="gemini")
        self.assertTrue(source.source_id.startswith("grounded_gemini_"))

    def test_source_id_unique(self):
        source1 = GroundedSearchSource(query="query one")
        source2 = GroundedSearchSource(query="query two")
        self.assertNotEqual(source1.source_id, source2.source_id)


class TestGroundedSearchSourceValidation(unittest.TestCase):
    """Tests for GroundedSearchSource validation."""

    def test_validate_empty_query(self):
        source = GroundedSearchSource(query="")
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_unsupported_provider(self):
        source = GroundedSearchSource(query="test")
        source.provider = "invalid"
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_missing_api_key(self):
        source = GroundedSearchSource(query="test", provider="gemini")
        source.api_key = None
        with self.assertRaises(ValidationError):
            source.validate()


class TestGroundedSearchSourceMetadata(unittest.TestCase):
    """Tests for GroundedSearchSource metadata."""

    def test_get_metadata_fields(self):
        source = GroundedSearchSource(
            query="test",
            provider="gemini",
            temperature=0.5,
            max_tokens=2048,
        )
        metadata = source.get_metadata()

        self.assertEqual(metadata["query"], "test")
        self.assertEqual(metadata["provider"], "gemini")
        self.assertEqual(metadata["temperature"], 0.5)
        self.assertEqual(metadata["max_tokens"], 2048)


class TestGroundedSearchSourceExtract(unittest.TestCase):
    """Tests for GroundedSearchSource extraction."""

    @patch.object(GroundedSearchSource, "_search_gemini")
    def test_extract_returns_raw_data(self, mock_search):
        mock_search.return_value = {
            "content": "Synthesized answer",
            "sources": [{"title": "Source 1", "url": "https://source1.com"}],
            "model": "gemini-2.5-flash",
        }

        source = GroundedSearchSource(query="test", provider="gemini", api_key="test")
        result = source.extract()

        self.assertEqual(result.content_type, "text")
        self.assertIn("Synthesized answer", result.content)
        self.assertIn("sources", result.metadata)

    @patch.object(GroundedSearchSource, "_search_gemini")
    def test_extract_includes_sources(self, mock_search):
        mock_search.return_value = {
            "content": "Answer",
            "sources": [
                {"title": "Source 1", "url": "https://s1.com"},
                {"title": "Source 2", "url": "https://s2.com"},
            ],
            "model": "gemini-2.5-flash",
        }

        source = GroundedSearchSource(query="test", provider="gemini", api_key="test")
        result = source.extract()

        self.assertEqual(result.metadata["source_count"], 2)
        self.assertEqual(len(source.get_sources()), 2)

    @patch.object(GroundedSearchSource, "_search_gemini")
    def test_extract_error_handling(self, mock_search):
        mock_search.side_effect = Exception("API Error")

        source = GroundedSearchSource(query="test", provider="gemini", api_key="test")
        with self.assertRaises(ExtractionError):
            source.extract()


class TestGroundedSearchSourceChainable(unittest.TestCase):
    """Tests for GroundedSearchSource chainable interface."""

    @patch.object(GroundedSearchSource, "extract")
    def test_invoke_calls_extract(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = GroundedSearchSource(query="test", api_key="test")
        source.invoke()

        mock_extract.assert_called_once()

    @patch.object(GroundedSearchSource, "extract")
    def test_invoke_with_query_override(self, mock_extract):
        mock_extract.return_value = MagicMock()

        source = GroundedSearchSource(query="original", api_key="test")
        source.invoke({"query": "new query"})

        self.assertEqual(source.query, "new query")


class TestGroundedSearchSourceProviders(unittest.TestCase):
    """Tests for GroundedSearchSource providers."""

    def test_all_providers_in_env_keys(self):
        providers = ["gemini", "perplexity"]
        for provider in providers:
            self.assertIn(provider, GroundedSearchSource.ENV_KEYS)

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_get_api_key_gemini(self):
        source = GroundedSearchSource(query="test", provider="gemini")
        self.assertEqual(source.api_key, "test-key")

    @patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"})
    def test_get_api_key_perplexity(self):
        source = GroundedSearchSource(query="test", provider="perplexity")
        self.assertEqual(source.api_key, "test-key")


if __name__ == "__main__":
    unittest.main()
