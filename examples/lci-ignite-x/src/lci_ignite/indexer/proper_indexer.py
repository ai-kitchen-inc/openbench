"""PROPER 2025 document indexer for Pinecone.

Indexes PROPER 2025 regulatory PDF documents into Pinecone vector store
for RAG-based retrieval by the HotspotAnalysisAgent and NarrativeHotspotAgent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def index_proper_docs(
    docs_dir: str | Path,
    pinecone_api_key: str,
    index_name: str = "lci-ignite",
    namespace: str = "proper-2025",
    embedding_model: str = "text-embedding-004",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> dict[str, Any]:
    """Index PROPER 2025 PDF documents into Pinecone.

    Uses OpenBench SDK's PDFSource for extraction, GoogleEmbeddingProvider
    for embeddings, and PineconeStore for storage.

    Args:
        docs_dir: Directory containing PROPER 2025 PDF files.
        pinecone_api_key: Pinecone API key.
        index_name: Pinecone index name.
        namespace: Pinecone namespace for isolation.
        embedding_model: Google embedding model name.
        chunk_size: Characters per chunk.
        chunk_overlap: Overlap between chunks.

    Returns:
        Dict with indexing statistics.
    """
    from openbench.data.sources.pdf import PDFSource
    from openbench.data.stores.base import ChunkingConfig
    from openbench.data.stores.pinecone import PineconeStore
    from openbench.intelligence.embeddings import GoogleEmbeddingProvider

    docs_path = Path(docs_dir)
    if not docs_path.exists():
        raise FileNotFoundError(f"Documents directory not found: {docs_dir}")

    pdf_files = list(docs_path.glob("**/*.pdf"))
    if not pdf_files:
        raise ValueError(f"No PDF files found in: {docs_dir}")

    logger.info("Found %d PDF files in %s", len(pdf_files), docs_dir)

    # Initialize components
    embedding_provider = GoogleEmbeddingProvider(model=embedding_model)
    dimension = embedding_provider.get_dimension(embedding_model)

    store = PineconeStore(
        index_name=index_name,
        namespace=namespace,
        api_key=pinecone_api_key,
        embedding_provider=embedding_provider,
        dimension=dimension,
        chunking_config=ChunkingConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ),
    )

    stats = {
        "files_processed": 0,
        "total_chunks": 0,
        "errors": [],
    }

    for pdf_file in pdf_files:
        try:
            logger.info("Indexing: %s", pdf_file.name)
            source = PDFSource(path=str(pdf_file))
            raw_data = source.extract()

            store.index(raw_data)

            stats["files_processed"] += 1
            logger.info("  Indexed: %s", pdf_file.name)

        except Exception as e:
            error_msg = f"Failed to index {pdf_file.name}: {e}"
            logger.error(error_msg)
            stats["errors"].append(error_msg)

    logger.info(
        "Indexing complete: %d files processed, %d errors",
        stats["files_processed"],
        len(stats["errors"]),
    )

    return stats
