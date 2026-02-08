"""Tests for embedding providers."""

import unittest
from unittest.mock import MagicMock, patch

from openbench.core.abstractions import EmbeddingProvider
from openbench.core.config import (
    EMBEDDING_MODELS,
    get_embedding_dimension,
    list_embedding_models,
)
from openbench.core.config import (
    get_embedding_provider as get_provider_name,
)
from openbench.intelligence.embeddings import (
    EMBEDDING_PROVIDERS,
    GoogleEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
    resolve_embedding_provider,
)


class TestEmbeddingProviderABC(unittest.TestCase):
    """Tests for EmbeddingProvider abstract base class."""

    def test_is_abstract(self):
        """Test that EmbeddingProvider cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            EmbeddingProvider()

    def test_concrete_class_works(self):
        """Test that a concrete implementation can be created."""

        class ConcreteProvider(EmbeddingProvider):
            @property
            def provider_name(self) -> str:
                return "test"

            @property
            def default_model(self) -> str:
                return "test-model"

            def get_dimension(self, model=None) -> int:
                return 256

            def embed(self, text, model=None):
                return [0.1] * 256

            def embed_batch(self, texts, model=None, batch_size=100):
                return [[0.1] * 256 for _ in texts]

        provider = ConcreteProvider()
        self.assertEqual(provider.provider_name, "test")
        self.assertEqual(provider.default_model, "test-model")
        self.assertEqual(provider.get_dimension(), 256)


class TestEmbeddingModelsRegistry(unittest.TestCase):
    """Tests for EMBEDDING_MODELS registry in config.py."""

    def test_openai_models_registered(self):
        """Test OpenAI embedding models are in registry."""
        self.assertIn("text-embedding-3-small", EMBEDDING_MODELS)
        self.assertIn("text-embedding-3-large", EMBEDDING_MODELS)
        self.assertIn("text-embedding-ada-002", EMBEDDING_MODELS)

    def test_google_models_registered(self):
        """Test Google embedding models are in registry."""
        self.assertIn("text-embedding-004", EMBEDDING_MODELS)
        self.assertIn("textembedding-gecko@003", EMBEDDING_MODELS)

    def test_model_has_dimension(self):
        """Test all models have dimension specified."""
        for model, info in EMBEDDING_MODELS.items():
            self.assertIn("dimension", info, f"Model {model} missing dimension")
            self.assertIsInstance(info["dimension"], int)
            self.assertGreater(info["dimension"], 0)

    def test_model_has_provider(self):
        """Test all models have provider specified."""
        for model, info in EMBEDDING_MODELS.items():
            self.assertIn("provider", info, f"Model {model} missing provider")
            self.assertIsInstance(info["provider"], str)

    def test_get_embedding_dimension(self):
        """Test get_embedding_dimension function."""
        self.assertEqual(get_embedding_dimension("text-embedding-3-small"), 1536)
        self.assertEqual(get_embedding_dimension("text-embedding-3-large"), 3072)
        self.assertEqual(get_embedding_dimension("text-embedding-004"), 768)

    def test_get_embedding_dimension_unknown_model(self):
        """Test get_embedding_dimension raises for unknown model."""
        with self.assertRaises(ValueError) as ctx:
            get_embedding_dimension("unknown-model")
        self.assertIn("Unknown embedding model", str(ctx.exception))

    def test_get_embedding_provider_name(self):
        """Test get_embedding_provider function from config."""
        self.assertEqual(get_provider_name("text-embedding-3-small"), "openai")
        self.assertEqual(get_provider_name("text-embedding-004"), "google")

    def test_list_embedding_models(self):
        """Test list_embedding_models function."""
        all_models = list_embedding_models()
        self.assertIsInstance(all_models, dict)
        self.assertGreaterEqual(len(all_models), 6)  # OpenAI (3) + Google (3)

    def test_list_embedding_models_by_provider(self):
        """Test list_embedding_models with provider filter."""
        openai_models = list_embedding_models(provider="openai")
        self.assertIn("text-embedding-3-small", openai_models)
        self.assertIn("text-embedding-3-large", openai_models)
        self.assertNotIn("text-embedding-004", openai_models)  # Google model


class TestOpenAIEmbeddingProvider(unittest.TestCase):
    """Tests for OpenAIEmbeddingProvider."""

    def test_init_with_valid_model(self):
        """Test initialization with valid model."""
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-small")
        self.assertEqual(provider.provider_name, "openai")
        self.assertEqual(provider.default_model, "text-embedding-3-small")

    def test_init_with_unknown_model_allowed(self):
        """Test initialization with unknown model is allowed (hybrid approach)."""
        # Should not raise - allows custom models
        provider = OpenAIEmbeddingProvider(model="text-embedding-4")
        self.assertEqual(provider.default_model, "text-embedding-4")

    def test_get_dimension_unknown_model_raises_helpful_error(self):
        """Test get_dimension with unknown model raises helpful error."""
        provider = OpenAIEmbeddingProvider(model="text-embedding-4")
        with self.assertRaises(ValueError) as ctx:
            provider.get_dimension()
        error_msg = str(ctx.exception)
        self.assertIn("Unknown model", error_msg)
        self.assertIn("dimension", error_msg)  # Suggests using dimension param
        self.assertIn("PR", error_msg)  # Suggests contributing

    def test_custom_dimension_override(self):
        """Test custom dimension parameter for new models."""
        provider = OpenAIEmbeddingProvider(model="text-embedding-4", dimension=2048)
        self.assertEqual(provider.get_dimension(), 2048)

    def test_get_dimension(self):
        """Test dimension retrieval for official models."""
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-small")
        self.assertEqual(provider.get_dimension(), 1536)

        provider_large = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        self.assertEqual(provider_large.get_dimension(), 3072)

    def test_list_models(self):
        """Test list_models returns available models."""
        provider = OpenAIEmbeddingProvider()
        models = provider.list_models()
        self.assertIn("text-embedding-3-small", models)
        self.assertEqual(models["text-embedding-3-small"], 1536)

    @patch("openai.OpenAI")
    def test_embed_calls_api(self, mock_openai_class):
        """Test embed method calls OpenAI API."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_client.embeddings.create.return_value = mock_response

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        result = provider.embed("test text")

        self.assertEqual(result, [0.1, 0.2, 0.3])
        mock_client.embeddings.create.assert_called_once()

    def test_embed_without_api_key_raises_error(self):
        """Test embed without API key raises error."""
        provider = OpenAIEmbeddingProvider()
        provider._api_key = None

        with self.assertRaises(ValueError) as ctx:
            provider.embed("test text")
        self.assertIn("API key required", str(ctx.exception))


class TestGoogleEmbeddingProvider(unittest.TestCase):
    """Tests for GoogleEmbeddingProvider."""

    def test_init_with_valid_model(self):
        """Test initialization with valid model."""
        provider = GoogleEmbeddingProvider(model="text-embedding-004")
        self.assertEqual(provider.provider_name, "google")
        self.assertEqual(provider.default_model, "text-embedding-004")

    def test_init_with_unknown_model_allowed(self):
        """Test initialization with unknown model is allowed (hybrid approach)."""
        provider = GoogleEmbeddingProvider(model="text-embedding-005")
        self.assertEqual(provider.default_model, "text-embedding-005")

    def test_get_dimension_unknown_model_raises_helpful_error(self):
        """Test get_dimension with unknown model raises helpful error."""
        provider = GoogleEmbeddingProvider(model="text-embedding-005")
        with self.assertRaises(ValueError) as ctx:
            provider.get_dimension()
        error_msg = str(ctx.exception)
        self.assertIn("Unknown model", error_msg)
        self.assertIn("dimension", error_msg)
        self.assertIn("PR", error_msg)

    def test_custom_dimension_override(self):
        """Test custom dimension parameter for new models."""
        provider = GoogleEmbeddingProvider(model="text-embedding-005", dimension=1024)
        self.assertEqual(provider.get_dimension(), 1024)

    def test_get_dimension(self):
        """Test dimension retrieval for official models."""
        provider = GoogleEmbeddingProvider(model="text-embedding-004")
        self.assertEqual(provider.get_dimension(), 768)

    def test_list_models(self):
        """Test list_models returns available models."""
        provider = GoogleEmbeddingProvider()
        models = provider.list_models()
        self.assertIn("text-embedding-004", models)
        self.assertEqual(models["text-embedding-004"], 768)


class TestEmbeddingProviderRegistry(unittest.TestCase):
    """Tests for EMBEDDING_PROVIDERS registry."""

    def test_all_providers_registered(self):
        """Test all providers are in registry."""
        self.assertIn("openai", EMBEDDING_PROVIDERS)
        self.assertIn("google", EMBEDDING_PROVIDERS)
        self.assertEqual(len(EMBEDDING_PROVIDERS), 2)

    def test_get_embedding_provider(self):
        """Test get_embedding_provider function."""
        provider = get_embedding_provider("openai")
        self.assertIsInstance(provider, OpenAIEmbeddingProvider)

        provider = get_embedding_provider("google")
        self.assertIsInstance(provider, GoogleEmbeddingProvider)

    def test_get_embedding_provider_with_model(self):
        """Test get_embedding_provider with specific model."""
        provider = get_embedding_provider("openai", model="text-embedding-3-large")
        self.assertEqual(provider.default_model, "text-embedding-3-large")
        self.assertEqual(provider.get_dimension(), 3072)

    def test_get_embedding_provider_unknown(self):
        """Test get_embedding_provider with unknown provider."""
        with self.assertRaises(ValueError) as ctx:
            get_embedding_provider("unknown")
        self.assertIn("Unknown embedding provider", str(ctx.exception))


class TestResolveEmbeddingProvider(unittest.TestCase):
    """Tests for resolve_embedding_provider function."""

    def test_resolve_with_provider_name(self):
        """Test resolution with explicit provider name."""
        provider = resolve_embedding_provider(provider="openai")
        self.assertIsInstance(provider, OpenAIEmbeddingProvider)

    def test_resolve_with_model_name(self):
        """Test resolution from model name."""
        provider = resolve_embedding_provider(model="text-embedding-3-large")
        self.assertIsInstance(provider, OpenAIEmbeddingProvider)
        self.assertEqual(provider.default_model, "text-embedding-3-large")

        provider = resolve_embedding_provider(model="text-embedding-004")
        self.assertIsInstance(provider, GoogleEmbeddingProvider)

    def test_resolve_default(self):
        """Test default resolution falls back to OpenAI."""
        provider = resolve_embedding_provider()
        self.assertIsInstance(provider, OpenAIEmbeddingProvider)
        self.assertEqual(provider.default_model, "text-embedding-3-small")

    def test_resolve_with_both_provider_and_model(self):
        """Test resolution with both provider and model."""
        provider = resolve_embedding_provider(provider="openai", model="text-embedding-3-large")
        self.assertIsInstance(provider, OpenAIEmbeddingProvider)
        self.assertEqual(provider.default_model, "text-embedding-3-large")


class TestEmbeddingMixinAutoDetection(unittest.TestCase):
    """Tests for EmbeddingMixin dimension auto-detection."""

    def test_auto_detect_from_explicit_dimension(self):
        """Test auto-detection uses explicit dimension if set."""
        from openbench.data.stores.base import EmbeddingMixin

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        obj._dimension = 512
        obj._resolved_dimension = None

        self.assertEqual(obj._get_dimension(), 512)

    def test_auto_detect_from_provider(self):
        """Test auto-detection from embedding provider."""
        from openbench.data.stores.base import EmbeddingMixin

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        obj._dimension = None
        obj._resolved_dimension = None
        obj._embedding_model = "text-embedding-3-large"

        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 3072
        obj._embedding_provider = mock_provider

        self.assertEqual(obj._get_dimension(), 3072)

    def test_auto_detect_fallback_to_default(self):
        """Test auto-detection falls back to 1536 as default."""
        from openbench.data.stores.base import EmbeddingMixin

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        obj._dimension = None
        obj._resolved_dimension = None
        obj._embedding_model = None

        # Mock provider without get_dimension
        mock_provider = MagicMock(spec=["embed"])
        obj._embedding_provider = mock_provider

        self.assertEqual(obj._get_dimension(), 1536)


if __name__ == "__main__":
    unittest.main()
