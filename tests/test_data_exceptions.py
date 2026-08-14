"""Tests for the data-layer and store exception hierarchies."""

from __future__ import annotations

import builtins
import unittest

from openbench.data.exceptions import (
    DataLayerError,
    ExtractionError,
    FileNotFoundError,
    SourceError,
    UnsupportedFormatError,
    ValidationError,
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


class TestDataLayerHierarchy(unittest.TestCase):
    def test_source_errors_are_data_layer_errors(self):
        for cls in (ExtractionError, ValidationError, FileNotFoundError, UnsupportedFormatError):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, SourceError))
                self.assertTrue(issubclass(cls, DataLayerError))

    def test_file_not_found_is_not_the_builtin(self):
        # The data-layer FileNotFoundError deliberately shadows the builtin
        # inside its own namespace; catching the builtin must not catch it.
        self.assertFalse(issubclass(FileNotFoundError, builtins.FileNotFoundError))


class TestStoreExceptionMessages(unittest.TestCase):
    def test_index_not_found_default_message(self):
        error = IndexNotFoundError("my-index")
        self.assertEqual(error.index_name, "my-index")
        self.assertIn("my-index", str(error))

    def test_store_connection_default_message(self):
        error = StoreConnectionError("pinecone")
        self.assertEqual(error.store_type, "pinecone")
        self.assertIn("pinecone", str(error))

    def test_dimension_mismatch_reports_both_sizes(self):
        error = DimensionMismatchError(expected=1536, got=3072)
        self.assertEqual((error.expected, error.got), (1536, 3072))
        self.assertIn("1536", str(error))
        self.assertIn("3072", str(error))

    def test_quota_exceeded_appends_retry_hint(self):
        self.assertNotIn("Retry after", str(QuotaExceededError()))
        error = QuotaExceededError(retry_after=30)
        self.assertEqual(error.retry_after, 30)
        self.assertIn("Retry after 30 seconds", str(error))

    def test_embedding_error_appends_text_length(self):
        self.assertNotIn("length", str(EmbeddingError()))
        self.assertIn("length 512", str(EmbeddingError(text_length=512)))

    def test_item_not_found_carries_item_id(self):
        error = ItemNotFoundError("chunk-1")
        self.assertEqual(error.item_id, "chunk-1")
        self.assertIn("chunk-1", str(error))

    def test_invalid_query_appends_reason(self):
        self.assertEqual(str(InvalidQueryError()), "Invalid query")
        self.assertEqual(str(InvalidQueryError(reason="empty text")), "Invalid query: empty text")

    def test_explicit_message_wins(self):
        self.assertEqual(str(IndexNotFoundError("x", message="custom")), "custom")

    def test_all_are_store_errors(self):
        errors = [
            IndexNotFoundError("i"),
            StoreConnectionError("s"),
            DimensionMismatchError(1, 2),
            QuotaExceededError(),
            EmbeddingError(),
            ItemNotFoundError("i"),
            InvalidQueryError(),
        ]
        for error in errors:
            with self.subTest(cls=type(error).__name__):
                self.assertIsInstance(error, StoreError)


if __name__ == "__main__":
    unittest.main()
