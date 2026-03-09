#!/usr/bin/env python3
"""One-time script to index PROPER 2025 documents into Pinecone.

Usage:
    python scripts/index_proper_docs.py /path/to/proper/docs

Requires:
    - GOOGLE_API_KEY (for embeddings)
    - PINECONE_API_KEY (for vector store)
"""

import argparse
import logging
import sys

from lci_ignite.config import LCIConfig
from lci_ignite.indexer.proper_indexer import index_proper_docs


def main():
    parser = argparse.ArgumentParser(description="Index PROPER 2025 documents")
    parser.add_argument("docs_dir", help="Directory containing PROPER 2025 PDFs")
    parser.add_argument("--index", default="lci-ignite", help="Pinecone index name")
    parser.add_argument("--namespace", default="proper-2025", help="Pinecone namespace")
    parser.add_argument("--chunk-size", type=int, default=1000, help="Chunk size")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="Chunk overlap")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = LCIConfig.from_env()
    missing = config.validate()
    if missing:
        print(f"Missing required config: {', '.join(missing)}")
        sys.exit(1)
    if not config.pinecone_api_key:
        print("PINECONE_API_KEY is required for indexing")
        sys.exit(1)

    stats = index_proper_docs(
        docs_dir=args.docs_dir,
        pinecone_api_key=config.pinecone_api_key,
        index_name=args.index,
        namespace=args.namespace,
        embedding_model=config.embedding_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    print("\nIndexing complete:")
    print(f"  Files processed: {stats['files_processed']}")
    if stats["errors"]:
        print(f"  Errors: {len(stats['errors'])}")
        for err in stats["errors"]:
            print(f"    - {err}")


if __name__ == "__main__":
    main()
