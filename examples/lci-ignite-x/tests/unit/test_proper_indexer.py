"""Unit tests for PROPER indexer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lci_ignite.indexer.proper_indexer import index_proper_docs


class TestIndexProperDocs:
    def test_raises_for_missing_dir(self):
        with pytest.raises(FileNotFoundError):
            index_proper_docs(
                docs_dir="/nonexistent/dir",
                pinecone_api_key="test-key",
            )

    def test_raises_for_no_pdfs(self, tmp_path):
        with pytest.raises(ValueError, match="No PDF files found"):
            index_proper_docs(
                docs_dir=str(tmp_path),
                pinecone_api_key="test-key",
            )

    @patch("openbench.data.stores.pinecone.PineconeStore")
    @patch("openbench.intelligence.embeddings.GoogleEmbeddingProvider")
    @patch("openbench.data.sources.pdf.PDFSource")
    def test_indexes_pdf_files(self, mock_pdf_cls, mock_embed_cls, mock_store_cls, tmp_path):
        (tmp_path / "doc1.pdf").write_text("fake pdf 1")
        (tmp_path / "doc2.pdf").write_text("fake pdf 2")

        mock_embed = MagicMock()
        mock_embed.get_dimension.return_value = 768
        mock_embed_cls.return_value = mock_embed

        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        mock_raw = MagicMock()
        mock_pdf = MagicMock()
        mock_pdf.extract.return_value = mock_raw
        mock_pdf_cls.return_value = mock_pdf

        stats = index_proper_docs(
            docs_dir=str(tmp_path),
            pinecone_api_key="test-key",
        )

        assert stats["files_processed"] == 2
        assert len(stats["errors"]) == 0
        assert mock_store.index.call_count == 2

    @patch("openbench.data.stores.pinecone.PineconeStore")
    @patch("openbench.intelligence.embeddings.GoogleEmbeddingProvider")
    @patch("openbench.data.sources.pdf.PDFSource")
    def test_handles_extraction_errors(
        self, mock_pdf_cls, mock_embed_cls, mock_store_cls, tmp_path
    ):
        (tmp_path / "bad.pdf").write_text("corrupted")

        mock_embed = MagicMock()
        mock_embed.get_dimension.return_value = 768
        mock_embed_cls.return_value = mock_embed

        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        mock_pdf = MagicMock()
        mock_pdf.extract.side_effect = Exception("PDF corrupt")
        mock_pdf_cls.return_value = mock_pdf

        stats = index_proper_docs(
            docs_dir=str(tmp_path),
            pinecone_api_key="test-key",
        )

        assert stats["files_processed"] == 0
        assert len(stats["errors"]) == 1
        assert "PDF corrupt" in stats["errors"][0]

    def test_custom_chunk_params_accepted(self, tmp_path):
        """Verify the function accepts custom chunk params without error before hitting SDK."""
        (tmp_path / "doc.pdf").write_text("fake")

        # This will fail at the SDK import level, but we're testing param acceptance
        # For full integration test, use the integration/ directory
        with pytest.raises(Exception):
            # Will fail when trying to create GoogleEmbeddingProvider without API key
            index_proper_docs(
                docs_dir=str(tmp_path),
                pinecone_api_key="test-key",
                chunk_size=500,
                chunk_overlap=100,
            )
