"""
RAG (Retrieval-Augmented Generation) setup for the LCA Compliance Checker.

Builds PineconeStore instances for:
  - lca-standards: 51 pre-indexed standards documents (ISO, PCR, KLH, impact categories)
  - lca-documents: user-uploaded LCA reports and profiles (indexed on demand)

Requires:
    - PINECONE_API_KEY environment variable
    - GOOGLE_API_KEY environment variable (for embeddings)
    - pip install openbench[vector,google]
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel file to skip re-indexing after first run
_SENTINEL_FILE = Path(__file__).parent / ".standards_indexed"

INDEX_NAME = os.getenv("PINECONE_INDEX", "openbench")
STANDARDS_NAMESPACE = "lca-standards"
DOCUMENTS_NAMESPACE = "japfa"


def build_standards_store() -> Any | None:
    """Create a PineconeStore for the lca-standards namespace.

    Returns:
        PineconeStore instance or None if dependencies are missing.
    """
    return _build_store(STANDARDS_NAMESPACE)


def build_documents_store() -> Any | None:
    """Create a PineconeStore for the lca-documents namespace.

    Returns:
        PineconeStore instance or None if dependencies are missing.
    """
    return _build_store(DOCUMENTS_NAMESPACE)


def _build_store(namespace: str) -> Any | None:
    """Build a PineconeStore for a given namespace.

    Returns None (with warning) if pinecone or google-genai is not installed.
    """
    try:
        from openbench.data.stores import PineconeStore
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider
    except ImportError as e:
        logger.warning("RAG dependencies not installed (%s). RAG disabled.", e)
        return None

    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        logger.warning("PINECONE_API_KEY not set. RAG disabled.")
        return None

    embedding_provider = GoogleEmbeddingProvider(model="gemini-embedding-001", dimension=768)

    return PineconeStore(
        index_name=INDEX_NAME,
        api_key=api_key,
        namespace=namespace,
        embedding_provider=embedding_provider,
        create_if_missing=False,
    )


def index_standards(store: Any) -> int:
    """Index all 51 standards documents into the lca-standards namespace.

    Skips if sentinel file exists (already indexed).

    Args:
        store: PineconeStore for lca-standards namespace.

    Returns:
        Number of documents indexed (0 if skipped).
    """
    if store is None:
        return 0

    if _SENTINEL_FILE.exists():
        logger.info("Standards already indexed (sentinel exists). Skipping.")
        return 0

    from openbench.core.abstractions import RawData

    documents = _build_standards_documents()
    logger.info("Indexing %d standards documents...", len(documents))

    indexed = 0
    for content, metadata in documents:
        raw = RawData(
            content=content,
            content_type="text",
            metadata=metadata,
        )
        try:
            store.index(raw)
            indexed += 1
        except Exception:
            logger.exception("Failed to index document: %s", metadata.get("req_id", "?"))

    if indexed == len(documents):
        _SENTINEL_FILE.write_text(f"indexed {indexed} documents\n")
        logger.info("Standards indexing complete: %d documents.", indexed)
    else:
        logger.warning(
            "Partial indexing: %d/%d succeeded. Sentinel not written.",
            indexed,
            len(documents),
        )

    return indexed


def _build_standards_documents() -> list[tuple[str, dict[str, Any]]]:
    """Build (content, metadata) pairs for all standards documents.

    Returns:
        List of 51 (content, metadata) tuples.
    """
    from standards_data import IMPACT_CATEGORIES, ISO_REQUIREMENTS, PCR_TEMPLATES, PEDOMAN_KLH

    documents: list[tuple[str, dict[str, Any]]] = []

    # ── ISO 14044 requirements (32 total) ──
    for phase_key, phase_data in ISO_REQUIREMENTS.items():
        iso_ref = phase_data["iso_ref"]
        title = phase_data["title"]
        for req in phase_data["shall_requirements"]:
            content = f"[{req['id']}] {req['text']} ({iso_ref} Section {req['ref']})"
            metadata = {
                "source_type": "iso",
                "phase": phase_key,
                "iso_ref": iso_ref,
                "req_id": req["id"],
                "clause_ref": req["ref"],
                "title": title,
            }
            documents.append((content, metadata))

    # ── PCR templates (4 total) ──
    for pcr_key, pcr_data in PCR_TEMPLATES.items():
        cats = ", ".join(pcr_data["mandatory_categories"])
        stages = "; ".join(f"{k}: {v}" for k, v in pcr_data["stages"].items())
        alloc = "; ".join(pcr_data["allocation_rules"])
        content = (
            f"{pcr_data['name']}. "
            f"System boundary: {pcr_data['system_boundary']}. "
            f"Mandatory categories: {cats}. "
            f"Stages: {stages}. "
            f"Allocation: {alloc}."
        )
        metadata = {
            "source_type": "pcr",
            "pcr_category": pcr_key,
            "pcr_name": pcr_data["name"],
        }
        documents.append((content, metadata))

    # ── Pedoman KLH requirements (7 total) ──
    for req in PEDOMAN_KLH["requirements"]:
        content = f"[{req['id']}] {req['text']}. Detail: {req['detail']}."
        metadata = {
            "source_type": "klh",
            "req_id": req["id"],
            "regulation_ref": PEDOMAN_KLH["regulation_ref"],
        }
        documents.append((content, metadata))

    # ── Impact categories (8 total) ──
    for code, cat_data in IMPACT_CATEGORIES.items():
        content = (
            f"{cat_data['name']} ({code}). "
            f"Unit: {cat_data['unit']}. "
            f"Method: {cat_data['method']}. "
            f"Description: {cat_data['description']}."
        )
        metadata = {
            "source_type": "impact_category",
            "category_code": code,
            "unit": cat_data["unit"],
            "method": cat_data["method"],
        }
        documents.append((content, metadata))

    return documents
