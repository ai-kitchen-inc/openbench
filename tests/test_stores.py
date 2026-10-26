"""Tests for data stores - chunking, base utilities, and PineconeStore."""

import unittest
from unittest.mock import MagicMock, patch

from openbench.core.abstractions import Query, RawData, SearchResult
from openbench.data.stores.base import (
    Chunk,
    ChunkingConfig,
    EmbeddingMixin,
    HybridSearchMixin,
    chunk_raw_data,
    chunk_text,
)
from openbench.data.stores.exceptions import (
    DimensionMismatchError,
    EmbeddingError,
    IndexNotFoundError,
    InvalidQueryError,
    ItemNotFoundError,
    QuotaExceededError,
    StoreConnectionError,
    StoreError,
)


class TestChunkingConfig(unittest.TestCase):
    """Tests for ChunkingConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ChunkingConfig()
        self.assertEqual(config.chunk_size, 1000)
        self.assertEqual(config.chunk_overlap, 200)
        self.assertEqual(config.separators, ["\n\n", "\n", ". ", ", ", " "])

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ChunkingConfig(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n", " "],
        )
        self.assertEqual(config.chunk_size, 500)
        self.assertEqual(config.chunk_overlap, 50)
        self.assertEqual(config.separators, ["\n", " "])

    def test_overlap_must_be_less_than_size(self):
        """Test that overlap must be less than chunk size."""
        with self.assertRaises(ValueError) as ctx:
            ChunkingConfig(chunk_size=100, chunk_overlap=100)
        self.assertIn("chunk_overlap must be less than chunk_size", str(ctx.exception))

    def test_chunk_size_must_be_positive(self):
        """Test that chunk size must be positive."""
        with self.assertRaises(ValueError) as ctx:
            ChunkingConfig(chunk_size=0)
        self.assertIn("chunk_size must be positive", str(ctx.exception))


class TestChunk(unittest.TestCase):
    """Tests for Chunk dataclass."""

    def test_chunk_creation(self):
        """Test creating a chunk."""
        chunk = Chunk(
            id="test-chunk-0",
            content="Hello, world!",
            index=0,
            total_chunks=1,
            metadata={"source": "test"},
        )
        self.assertEqual(chunk.id, "test-chunk-0")
        self.assertEqual(chunk.content, "Hello, world!")
        self.assertEqual(chunk.index, 0)
        self.assertEqual(chunk.total_chunks, 1)
        self.assertEqual(chunk.metadata, {"source": "test"})

    def test_content_hash(self):
        """Test content hash generation."""
        chunk = Chunk(
            id="test-chunk-0",
            content="Hello, world!",
            index=0,
            total_chunks=1,
        )
        hash_value = chunk.content_hash
        self.assertTrue(hash_value.startswith("sha256:"))
        self.assertEqual(len(hash_value), 23)  # "sha256:" + 16 hex chars

    def test_same_content_same_hash(self):
        """Test that same content produces same hash."""
        chunk1 = Chunk(id="1", content="Hello", index=0, total_chunks=1)
        chunk2 = Chunk(id="2", content="Hello", index=1, total_chunks=2)
        self.assertEqual(chunk1.content_hash, chunk2.content_hash)

    def test_different_content_different_hash(self):
        """Test that different content produces different hash."""
        chunk1 = Chunk(id="1", content="Hello", index=0, total_chunks=1)
        chunk2 = Chunk(id="2", content="World", index=0, total_chunks=1)
        self.assertNotEqual(chunk1.content_hash, chunk2.content_hash)


class TestChunkText(unittest.TestCase):
    """Tests for chunk_text function."""

    def test_empty_text(self):
        """Test chunking empty text."""
        result = chunk_text("")
        self.assertEqual(result, [])

    def test_whitespace_only(self):
        """Test chunking whitespace-only text."""
        result = chunk_text("   \n\n   ")
        self.assertEqual(result, [])

    def test_small_text_single_chunk(self):
        """Test that small text returns single chunk."""
        text = "This is a short text."
        result = chunk_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], text)

    def test_text_at_chunk_size_limit(self):
        """Test text exactly at chunk size limit."""
        config = ChunkingConfig(chunk_size=20, chunk_overlap=5)
        text = "This is twenty chars"
        result = chunk_text(text, config)
        self.assertEqual(len(result), 1)

    def test_long_text_multiple_chunks(self):
        """Test that long text is split into multiple chunks."""
        config = ChunkingConfig(chunk_size=50, chunk_overlap=10)
        text = "This is a longer text. " * 10
        result = chunk_text(text, config)
        self.assertGreater(len(result), 1)

    def test_splits_on_paragraph(self):
        """Test that text splits on paragraph boundaries."""
        config = ChunkingConfig(chunk_size=50, chunk_overlap=10)
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = chunk_text(text, config)
        # Should split at paragraph boundaries
        self.assertGreater(len(result), 1)

    def test_splits_on_sentence(self):
        """Test that text splits on sentence boundaries."""
        config = ChunkingConfig(chunk_size=30, chunk_overlap=5)
        text = "First sentence. Second sentence. Third sentence."
        result = chunk_text(text, config)
        self.assertGreater(len(result), 1)

    def test_overlap_preserved(self):
        """Test that chunk overlap is preserved."""
        config = ChunkingConfig(chunk_size=20, chunk_overlap=5, separators=[" "])
        text = "one two three four five six seven eight nine ten"
        result = chunk_text(text, config)

        # Check that there's some overlap between consecutive chunks
        if len(result) >= 2:
            # At least some content should appear in multiple chunks
            all_content = " ".join(result)
            # The total length with overlap should be >= original
            self.assertGreaterEqual(len(all_content), len(text))


class TestChunkRawData(unittest.TestCase):
    """Tests for chunk_raw_data function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_source = MagicMock()
        self.mock_source.source_id = "test-source"
        self.mock_source.source_type = "test"

    def test_chunk_string_content(self):
        """Test chunking RawData with string content."""
        data = RawData(
            content="Hello, world! This is a test.",
            content_type="text",
            metadata={"author": "test"},
            source=self.mock_source,
        )
        result = chunk_raw_data(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "Hello, world! This is a test.")
        self.assertEqual(result[0].metadata["source_id"], "test-source")
        self.assertEqual(result[0].metadata["source_type"], "test")
        self.assertEqual(result[0].metadata["author"], "test")

    def test_chunk_bytes_content(self):
        """Test chunking RawData with bytes content."""
        data = RawData(
            content=b"Hello, world!",
            content_type="binary",
            metadata={},
            source=self.mock_source,
        )
        result = chunk_raw_data(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "Hello, world!")

    def test_chunk_with_custom_config(self):
        """Test chunking with custom configuration."""
        config = ChunkingConfig(chunk_size=20, chunk_overlap=5)
        data = RawData(
            content="This is a longer text that should be split into multiple chunks.",
            content_type="text",
            metadata={},
            source=self.mock_source,
        )
        result = chunk_raw_data(data, config)
        self.assertGreater(len(result), 1)

    def test_chunk_ids_are_unique(self):
        """Test that chunk IDs are unique."""
        config = ChunkingConfig(chunk_size=20, chunk_overlap=5)
        data = RawData(
            content="A" * 100,
            content_type="text",
            metadata={},
            source=self.mock_source,
        )
        result = chunk_raw_data(data, config)
        ids = [chunk.id for chunk in result]
        self.assertEqual(len(ids), len(set(ids)))

    def test_chunk_indices_are_sequential(self):
        """Test that chunk indices are sequential."""
        config = ChunkingConfig(chunk_size=20, chunk_overlap=5)
        data = RawData(
            content="A" * 100,
            content_type="text",
            metadata={},
            source=self.mock_source,
        )
        result = chunk_raw_data(data, config)
        for i, chunk in enumerate(result):
            self.assertEqual(chunk.index, i)
            self.assertEqual(chunk.total_chunks, len(result))

    def test_empty_content(self):
        """Test chunking empty content."""
        data = RawData(
            content="",
            content_type="text",
            metadata={},
            source=self.mock_source,
        )
        result = chunk_raw_data(data)
        self.assertEqual(result, [])


class TestEmbeddingMixin(unittest.TestCase):
    """Tests for EmbeddingMixin."""

    def test_embed_with_provider(self):
        """Test embedding with explicit provider."""

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        mock_provider = MagicMock()
        mock_provider.embed.return_value = [0.1, 0.2, 0.3]
        obj._embedding_provider = mock_provider
        obj._embedding_model = None

        result = obj._embed("test text")
        self.assertEqual(result, [0.1, 0.2, 0.3])
        mock_provider.embed.assert_called_once_with("test text", model=None)

    def test_embed_batch_with_embed_batch_method(self):
        """Test batch embedding with provider that has embed_batch."""

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        mock_provider = MagicMock()
        mock_provider.embed_batch.return_value = [[0.1], [0.2], [0.3]]
        obj._embedding_provider = mock_provider
        obj._embedding_model = None

        result = obj._embed_batch(["a", "b", "c"])
        self.assertEqual(result, [[0.1], [0.2], [0.3]])

    def test_embed_batch_fallback(self):
        """Test batch embedding fallback to individual embed calls."""

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        mock_provider = MagicMock(spec=["embed"])
        mock_provider.embed.side_effect = [[0.1], [0.2], [0.3]]
        obj._embedding_provider = mock_provider
        obj._embedding_model = None

        result = obj._embed_batch(["a", "b", "c"])
        self.assertEqual(result, [[0.1], [0.2], [0.3]])
        self.assertEqual(mock_provider.embed.call_count, 3)

    def test_no_provider_raises_error(self):
        """Test that missing provider raises ValueError when resolution fails."""

        class TestClass(EmbeddingMixin):
            pass

        obj = TestClass()
        # Mock the resolve_embedding_provider to simulate failure
        with patch("openbench.intelligence.embeddings.resolve_embedding_provider") as mock_resolve:
            mock_resolve.side_effect = Exception("No provider available")
            with self.assertRaises(ValueError) as ctx:
                obj._get_embedding_provider()
            self.assertIn("No embedding provider configured", str(ctx.exception))


class TestStoreExceptions(unittest.TestCase):
    """Tests for store exceptions."""

    def test_store_error(self):
        """Test base StoreError."""
        error = StoreError("Something went wrong")
        self.assertEqual(str(error), "Something went wrong")

    def test_index_not_found_error(self):
        """Test IndexNotFoundError."""
        error = IndexNotFoundError("my-index")
        self.assertEqual(error.index_name, "my-index")
        self.assertIn("my-index", str(error))

    def test_store_connection_error(self):
        """Test StoreConnectionError."""
        error = StoreConnectionError("pinecone")
        self.assertEqual(error.store_type, "pinecone")
        self.assertIn("pinecone", str(error))

    def test_dimension_mismatch_error(self):
        """Test DimensionMismatchError."""
        error = DimensionMismatchError(expected=1536, got=768)
        self.assertEqual(error.expected, 1536)
        self.assertEqual(error.got, 768)
        self.assertIn("1536", str(error))
        self.assertIn("768", str(error))

    def test_quota_exceeded_error(self):
        """Test QuotaExceededError."""
        error = QuotaExceededError(retry_after=60)
        self.assertEqual(error.retry_after, 60)
        self.assertIn("60", str(error))

    def test_embedding_error(self):
        """Test EmbeddingError."""
        error = EmbeddingError(text_length=1000)
        self.assertEqual(error.text_length, 1000)
        self.assertIn("1000", str(error))

    def test_item_not_found_error(self):
        """Test ItemNotFoundError."""
        error = ItemNotFoundError("item-123")
        self.assertEqual(error.item_id, "item-123")
        self.assertIn("item-123", str(error))

    def test_invalid_query_error(self):
        """Test InvalidQueryError."""
        error = InvalidQueryError(reason="missing text")
        self.assertEqual(error.reason, "missing text")
        self.assertIn("missing text", str(error))


class TestHybridSearchMixin(unittest.TestCase):
    """Tests for HybridSearchMixin BM25 and hybrid reranking."""

    def test_bm25_score_basic(self):
        """Test BM25 score for matching terms."""
        score = HybridSearchMixin.bm25_score(["python", "programming"], "python programming is fun")
        self.assertGreater(score, 0.0)

    def test_bm25_score_no_match(self):
        """Test BM25 score when no terms match."""
        score = HybridSearchMixin.bm25_score(["python", "programming"], "java development guide")
        self.assertEqual(score, 0.0)

    def test_bm25_score_repeated_terms(self):
        """Test BM25 score increases with term frequency."""
        score_once = HybridSearchMixin.bm25_score(["python"], "python is great")
        score_twice = HybridSearchMixin.bm25_score(
            ["python"], "python python tutorial about python"
        )
        self.assertGreater(score_twice, score_once)

    def test_bm25_score_case_insensitive(self):
        """Test BM25 scoring is case insensitive for document."""
        score = HybridSearchMixin.bm25_score(["python"], "Python Programming PYTHON")
        self.assertGreater(score, 0.0)

    def test_hybrid_rerank_empty(self):
        """Test hybrid rerank with empty inputs."""
        items, scores = HybridSearchMixin.hybrid_rerank([], [], "query")
        self.assertEqual(items, [])
        self.assertEqual(scores, [])

    def test_hybrid_rerank_reorders_by_keyword(self):
        """Test that hybrid rerank boosts keyword-matching results."""
        items = [
            {"content": "unrelated document about cats"},
            {"content": "python programming tutorial guide"},
        ]
        vector_scores = [0.9, 0.7]  # First has higher vector score

        reranked_items, _reranked_scores = HybridSearchMixin.hybrid_rerank(
            items,
            vector_scores,
            "python programming",
            vector_weight=0.5,
            keyword_weight=0.5,
        )

        # Second item should now rank higher due to keyword match
        self.assertEqual(reranked_items[0]["content"], "python programming tutorial guide")

    def test_hybrid_rerank_preserves_items(self):
        """Test that hybrid rerank preserves all items."""
        items = [
            {"content": "doc a"},
            {"content": "doc b"},
            {"content": "doc c"},
        ]
        scores = [0.8, 0.7, 0.6]

        reranked_items, reranked_scores = HybridSearchMixin.hybrid_rerank(
            items, scores, "test query"
        )

        self.assertEqual(len(reranked_items), 3)
        self.assertEqual(len(reranked_scores), 3)

    def test_hybrid_rerank_weights(self):
        """Test that vector_weight=1.0 preserves original order."""
        items = [
            {"content": "first doc with keywords"},
            {"content": "second doc"},
        ]
        scores = [0.9, 0.5]

        reranked_items, _ = HybridSearchMixin.hybrid_rerank(
            items, scores, "keywords", vector_weight=1.0, keyword_weight=0.0
        )

        # Should preserve original order (vector only)
        self.assertEqual(reranked_items[0]["content"], "first doc with keywords")

    def test_hybrid_rerank_zero_vector_scores(self):
        """Test hybrid rerank when all vector scores are zero."""
        items = [
            {"content": "no match"},
            {"content": "python tutorial"},
        ]
        scores = [0.0, 0.0]

        reranked_items, _reranked_scores = HybridSearchMixin.hybrid_rerank(items, scores, "python")

        # Should still work, keyword score determines ranking
        self.assertEqual(len(reranked_items), 2)


class TestPineconeStore(unittest.TestCase):
    """Tests for PineconeStore (mocked)."""

    def setUp(self):
        """Set up test fixtures."""
        # Patch pinecone import
        self.pinecone_patch = patch.dict(
            "sys.modules",
            {"pinecone": MagicMock()},
        )
        self.pinecone_patch.start()

    def tearDown(self):
        """Clean up patches."""
        self.pinecone_patch.stop()

    @patch.dict("os.environ", {"PINECONE_API_KEY": "test-key"})
    def test_init_with_env_key(self):
        """Test initialization with environment API key."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(index_name="test-index")
        self.assertEqual(store._index_name, "test-index")
        self.assertEqual(store._api_key, "test-key")

    def test_init_with_explicit_key(self):
        """Test initialization with explicit API key."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="explicit-key",
        )
        self.assertEqual(store._api_key, "explicit-key")

    def test_store_type(self):
        """Test store_type property."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )
        self.assertEqual(store.store_type, "vector")

    def test_namespace_with_explicit_value(self):
        """Test namespace resolution with explicit value."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            namespace="my-namespace",
        )
        self.assertEqual(store.namespace, "my-namespace")

    def test_namespace_with_project(self):
        """Test namespace resolution with project context."""
        from openbench.core.context import ProjectContext
        from openbench.data.stores.pinecone import PineconeStore

        project = ProjectContext(name="test-project")
        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            project=project,
        )
        self.assertEqual(store.namespace, project.namespace)

    def test_build_filter_simple(self):
        """Test simple filter building."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )

        result = store._build_filter({"source_type": "pdf"})
        self.assertEqual(result, {"source_type": {"$eq": "pdf"}})

    def test_build_filter_with_operators(self):
        """Test filter building with operators."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )

        result = store._build_filter(
            {
                "count": {"$gt": 10},
                "$or": [{"a": 1}, {"b": 2}],
            }
        )
        self.assertEqual(result["count"], {"$gt": 10})
        self.assertIn("$or", result)

    def test_build_filter_empty(self):
        """Test empty filter building."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )

        result = store._build_filter({})
        self.assertEqual(result, {})

    def test_index_method(self):
        """Test index method."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_index = MagicMock()

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )

        # Directly set the _index to bypass lazy initialization
        store._index = mock_index
        store._client = MagicMock()

        # Mock embedding
        store._embed_batch = MagicMock(return_value=[[0.1] * 1536])

        mock_source = MagicMock()
        mock_source.source_id = "test-source"
        mock_source.source_type = "test"

        data = RawData(
            content="Test content",
            content_type="text",
            metadata={},
            source=mock_source,
        )

        result = store.index(data)
        self.assertEqual(result, "test-source")
        mock_index.upsert.assert_called()

    def test_search_method(self):
        """Test search method."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_index = MagicMock()

        # Mock query response
        mock_match = MagicMock()
        mock_match.id = "test-id"
        mock_match.score = 0.9
        mock_match.metadata = {"content": "test content"}

        mock_response = MagicMock()
        mock_response.matches = [mock_match]
        mock_index.query.return_value = mock_response

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )

        # Directly set the _index to bypass lazy initialization
        store._index = mock_index
        store._client = MagicMock()

        # Mock embedding
        store._embed = MagicMock(return_value=[0.1] * 1536)

        query = Query(text="test query", limit=10)
        result = store.search(query)

        self.assertIsInstance(result, SearchResult)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["id"], "test-id")
        self.assertEqual(result.scores[0], 0.9)


class TestPineconeStoreDimensionValidation(unittest.TestCase):
    """Tests for PineconeStore dimension validation on existing indexes."""

    def setUp(self):
        """Set up test fixtures."""
        self.pinecone_patch = patch.dict(
            "sys.modules",
            {"pinecone": MagicMock()},
        )
        self.pinecone_patch.start()

    def tearDown(self):
        """Clean up patches."""
        self.pinecone_patch.stop()

    def test_dimension_mismatch_raises_error(self):
        """Test that mismatched dimensions raise DimensionMismatchError."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 3072  # Provider outputs 3072

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            embedding_provider=mock_provider,
        )

        # Mock client that returns existing index with dim=768
        mock_client = MagicMock()
        mock_idx_info = MagicMock()
        mock_idx_info.name = "test-index"
        mock_client.list_indexes.return_value = [mock_idx_info]
        mock_desc = MagicMock()
        mock_desc.dimension = 768
        mock_client.describe_index.return_value = mock_desc
        store._client = mock_client

        with self.assertRaises(DimensionMismatchError) as ctx:
            store._get_or_create_index()

        self.assertEqual(ctx.exception.expected, 768)
        self.assertEqual(ctx.exception.got, 3072)
        self.assertIn("dimension=768", str(ctx.exception))

    def test_matching_dimensions_no_error(self):
        """Test that matching dimensions don't raise an error."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 768

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            embedding_provider=mock_provider,
        )

        mock_client = MagicMock()
        mock_idx_info = MagicMock()
        mock_idx_info.name = "test-index"
        mock_client.list_indexes.return_value = [mock_idx_info]
        mock_desc = MagicMock()
        mock_desc.dimension = 768
        mock_client.describe_index.return_value = mock_desc
        store._client = mock_client

        # Should not raise
        store._get_or_create_index()

    def test_no_provider_skips_validation(self):
        """Test that missing provider skips dimension validation."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )

        mock_client = MagicMock()
        mock_idx_info = MagicMock()
        mock_idx_info.name = "test-index"
        mock_client.list_indexes.return_value = [mock_idx_info]
        store._client = mock_client

        # Should not raise (no provider to validate)
        store._get_or_create_index()

    def test_error_message_includes_fix(self):
        """Test that error message includes actionable fix."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 3072
        type(mock_provider).__name__ = "GoogleEmbeddingProvider"

        store = PineconeStore(
            index_name="my-index",
            api_key="test-key",
            embedding_provider=mock_provider,
        )

        mock_client = MagicMock()
        mock_idx_info = MagicMock()
        mock_idx_info.name = "my-index"
        mock_client.list_indexes.return_value = [mock_idx_info]
        mock_desc = MagicMock()
        mock_desc.dimension = 768
        mock_client.describe_index.return_value = mock_desc
        store._client = mock_client

        with self.assertRaises(DimensionMismatchError) as ctx:
            store._get_or_create_index()

        msg = str(ctx.exception)
        self.assertIn("GoogleEmbeddingProvider", msg)
        self.assertIn("3072", msg)
        self.assertIn("768", msg)
        self.assertIn("dimension=768", msg)


class TestEmbeddingProviderDimensionScaling(unittest.TestCase):
    """Tests for embedding provider dimension scaling (MRL/shortening)."""

    @patch("google.generativeai.embed_content")
    def test_google_provider_passes_output_dimensionality(self, mock_embed):
        """Test GoogleEmbeddingProvider passes output_dimensionality to API."""
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider

        mock_embed.return_value = {"embedding": [0.1] * 768}

        provider = GoogleEmbeddingProvider(
            model="gemini-embedding-001",
            api_key="test-key",
            dimension=768,
        )
        provider._configured = True

        provider.embed("test text")

        mock_embed.assert_called_once()
        call_kwargs = mock_embed.call_args
        self.assertEqual(call_kwargs[1].get("output_dimensionality"), 768)

    @patch("google.generativeai.embed_content")
    def test_google_provider_no_dimension_no_param(self, mock_embed):
        """Test GoogleEmbeddingProvider omits output_dimensionality when not set."""
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider

        mock_embed.return_value = {"embedding": [0.1] * 3072}

        provider = GoogleEmbeddingProvider(
            model="gemini-embedding-001",
            api_key="test-key",
        )
        provider._configured = True

        provider.embed("test text")

        call_kwargs = mock_embed.call_args
        self.assertNotIn("output_dimensionality", call_kwargs[1])

    def test_openai_provider_passes_dimensions(self):
        """Test OpenAIEmbeddingProvider passes dimensions to API."""
        from openbench.intelligence.embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            api_key="test-key",
            dimension=256,
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 256)]
        mock_client.embeddings.create.return_value = mock_response
        provider._client = mock_client

        provider.embed("test text")

        call_kwargs = mock_client.embeddings.create.call_args
        self.assertEqual(call_kwargs[1].get("dimensions"), 256)

    def test_openai_provider_no_dimension_no_param(self):
        """Test OpenAIEmbeddingProvider omits dimensions when not set."""
        from openbench.intelligence.embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            api_key="test-key",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_client.embeddings.create.return_value = mock_response
        provider._client = mock_client

        provider.embed("test text")

        call_kwargs = mock_client.embeddings.create.call_args
        self.assertNotIn("dimensions", call_kwargs[1])


class TestPineconeStoreHybridSearch(unittest.TestCase):
    """Tests for PineconeStore hybrid search integration."""

    def setUp(self):
        """Set up test fixtures."""
        self.pinecone_patch = patch.dict(
            "sys.modules",
            {"pinecone": MagicMock()},
        )
        self.pinecone_patch.start()

    def tearDown(self):
        """Clean up patches."""
        self.pinecone_patch.stop()

    def test_hybrid_search_disabled_by_default(self):
        """Test hybrid search is disabled by default."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
        )
        self.assertFalse(store._hybrid_search)

    def test_hybrid_search_enabled(self):
        """Test hybrid search can be enabled."""
        from openbench.data.stores.pinecone import PineconeStore

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            hybrid_search=True,
            vector_weight=0.6,
        )
        self.assertTrue(store._hybrid_search)
        self.assertEqual(store._vector_weight, 0.6)

    def test_hybrid_search_reranks_results(self):
        """Test that hybrid search reranks results."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_index = MagicMock()

        # Create mock matches: first has high vector score but no keyword match
        mock_match1 = MagicMock()
        mock_match1.id = "id1"
        mock_match1.score = 0.95
        mock_match1.metadata = {"content": "unrelated document about animals"}

        mock_match2 = MagicMock()
        mock_match2.id = "id2"
        mock_match2.score = 0.70
        mock_match2.metadata = {"content": "python programming tutorial basics"}

        mock_response = MagicMock()
        mock_response.matches = [mock_match1, mock_match2]
        mock_index.query.return_value = mock_response

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            hybrid_search=True,
            vector_weight=0.3,  # Low vector weight, high keyword weight
        )
        store._index = mock_index
        store._client = MagicMock()
        store._embed = MagicMock(return_value=[0.1] * 1536)

        query = Query(text="python programming", limit=10)
        result = store.search(query)

        # With low vector weight and high keyword weight,
        # the python doc should be ranked first
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.items[0]["id"], "id2")

    def test_hybrid_search_disabled_preserves_order(self):
        """Test that disabled hybrid search preserves vector order."""
        from openbench.data.stores.pinecone import PineconeStore

        mock_index = MagicMock()

        mock_match1 = MagicMock()
        mock_match1.id = "id1"
        mock_match1.score = 0.95
        mock_match1.metadata = {"content": "no keyword match here"}

        mock_match2 = MagicMock()
        mock_match2.id = "id2"
        mock_match2.score = 0.70
        mock_match2.metadata = {"content": "python programming"}

        mock_response = MagicMock()
        mock_response.matches = [mock_match1, mock_match2]
        mock_index.query.return_value = mock_response

        store = PineconeStore(
            index_name="test-index",
            api_key="test-key",
            hybrid_search=False,
        )
        store._index = mock_index
        store._client = MagicMock()
        store._embed = MagicMock(return_value=[0.1] * 1536)

        query = Query(text="python programming", limit=10)
        result = store.search(query)

        # Original vector order preserved
        self.assertEqual(result.items[0]["id"], "id1")
        self.assertEqual(result.items[1]["id"], "id2")


if __name__ == "__main__":
    unittest.main()
