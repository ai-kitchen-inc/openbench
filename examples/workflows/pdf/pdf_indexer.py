"""
PDF Indexer Workflow - Index PDF documents to Pinecone

Demonstrates data ingestion workflow:
    PDFSource -> PineconeStore (with embeddings)

This workflow ONLY indexes data, no LLM processing.
Use this to build a knowledge base from PDF documents.

Usage:
    python examples/workflows/pdf/pdf_indexer.py <pdf-path>
    python examples/workflows/pdf/pdf_indexer.py document.pdf --namespace my-project
    python examples/workflows/pdf/pdf_indexer.py ./docs/*.pdf --batch

Requires:
    - PINECONE_API_KEY environment variable
    - GOOGLE_API_KEY environment variable (for embeddings)
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from typing import List

from openbench.data.sources import PDFSource
from openbench.data.stores import PineconeStore
from openbench.intelligence import GoogleEmbeddingProvider
from openbench.data.stores.base import ChunkingConfig


def check_api_keys():
    """Check required API keys."""
    missing = []
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")

    if missing:
        print("Error: Missing environment variables:")
        for key in missing:
            print(f"  - {key}")
        sys.exit(1)


def create_store(
    index_name: str = "openbench",
    namespace: str = "knowledge-base",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> PineconeStore:
    """Create PineconeStore with Google embeddings."""

    embedding_provider = GoogleEmbeddingProvider(model="text-embedding-004")

    chunking_config = ChunkingConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    store = PineconeStore(
        index_name=index_name,
        namespace=namespace,
        embedding_provider=embedding_provider,
        chunking_config=chunking_config,
        create_if_missing=True,
    )

    return store


def index_pdf(
    pdf_path: str,
    store: PineconeStore,
    metadata: dict = None,
) -> dict:
    """Index a single PDF to Pinecone.

    Args:
        pdf_path: Path to PDF file
        store: PineconeStore instance
        metadata: Additional metadata to attach

    Returns:
        Dict with indexing results
    """
    pdf_file = Path(pdf_path)

    if not pdf_file.exists():
        return {"status": "error", "error": f"File not found: {pdf_path}"}

    print(f"\n  Processing: {pdf_file.name}")

    try:
        # Extract PDF content
        source = PDFSource(path=str(pdf_file))
        raw_data = source.extract()

        # Add custom metadata
        if metadata:
            raw_data.metadata.update(metadata)

        # Add source filename
        raw_data.metadata["filename"] = pdf_file.name
        raw_data.metadata["file_path"] = str(pdf_file.absolute())

        # Index to Pinecone
        source_id = store.index(raw_data)

        content_length = len(raw_data.content) if raw_data.content else 0

        print(f"    ✓ Indexed: {content_length:,} chars")
        print(f"    ✓ Source ID: {source_id}")

        return {
            "status": "success",
            "source_id": source_id,
            "filename": pdf_file.name,
            "content_length": content_length,
        }

    except Exception as e:
        print(f"    ✗ Error: {e}")
        return {"status": "error", "error": str(e), "filename": pdf_file.name}


def index_batch(
    pdf_paths: List[str],
    store: PineconeStore,
    metadata: dict = None,
) -> List[dict]:
    """Index multiple PDFs to Pinecone.

    Args:
        pdf_paths: List of PDF file paths
        store: PineconeStore instance
        metadata: Additional metadata for all files

    Returns:
        List of indexing results
    """
    results = []

    for pdf_path in pdf_paths:
        result = index_pdf(pdf_path, store, metadata)
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Index PDF documents to Pinecone vector store"
    )
    parser.add_argument("pdf", nargs="+", help="PDF file(s) or glob pattern")
    parser.add_argument("--index", default="openbench", help="Pinecone index name")
    parser.add_argument("--namespace", default="knowledge-base", help="Pinecone namespace")
    parser.add_argument("--chunk-size", type=int, default=1000, help="Chunk size for splitting")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="Overlap between chunks")
    parser.add_argument("--tag", help="Tag to add to all documents")
    parser.add_argument("--batch", action="store_true", help="Process as batch (glob patterns)")
    args = parser.parse_args()

    print("=" * 60)
    print("PDF Indexer - OpenBench")
    print("=" * 60)
    print(f"\nIndex: {args.index}")
    print(f"Namespace: {args.namespace}")
    print(f"Chunk size: {args.chunk_size}")
    print(f"Chunk overlap: {args.chunk_overlap}")

    check_api_keys()

    # Expand glob patterns if batch mode
    pdf_files = []
    for pattern in args.pdf:
        if args.batch or "*" in pattern:
            expanded = glob.glob(pattern)
            pdf_files.extend(expanded)
        else:
            pdf_files.append(pattern)

    if not pdf_files:
        print("\nError: No PDF files found")
        sys.exit(1)

    print(f"\nFiles to index: {len(pdf_files)}")

    # Create store
    store = create_store(
        index_name=args.index,
        namespace=args.namespace,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    # Prepare metadata
    metadata = {}
    if args.tag:
        metadata["tag"] = args.tag

    # Index files
    print("\n" + "-" * 60)
    print("Indexing...")
    print("-" * 60)

    results = index_batch(pdf_files, store, metadata)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "error"]

    print(f"\n  Success: {len(success)}")
    print(f"  Failed:  {len(failed)}")

    if success:
        total_chars = sum(r.get("content_length", 0) for r in success)
        print(f"  Total indexed: {total_chars:,} characters")

    if failed:
        print("\n  Failed files:")
        for r in failed:
            print(f"    - {r.get('filename', 'unknown')}: {r.get('error', 'unknown error')}")

    # Show index stats
    print("\n" + "-" * 60)
    print("Index Stats")
    print("-" * 60)
    try:
        stats = store.describe_index()
        print(f"  Index: {stats['index_name']}")
        print(f"  Dimension: {stats['dimension']}")
        print(f"  Total vectors: {stats['total_vector_count']}")
        if stats.get('namespaces'):
            for ns, data in stats['namespaces'].items():
                print(f"  Namespace '{ns}': {data['vector_count']} vectors")
    except Exception as e:
        print(f"  Could not get stats: {e}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
