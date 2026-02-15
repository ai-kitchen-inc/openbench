---
name: data-layer
description: Working with OpenBench data layer - vector stores, chunking, embeddings, and RAG patterns. Use when implementing PineconeStore, chunking documents, generating embeddings, or building RAG workflows.
---

# Data Layer

OpenBench data layer handles vector stores, chunking, embeddings, and RAG patterns.

## Chunking

Split documents into chunks for vector indexing:

```python
from openbench.data.stores import ChunkingConfig, chunk_text, chunk_raw_data, Chunk

# Configure chunking
config = ChunkingConfig(
    chunk_size=1000,      # Max chars per chunk
    chunk_overlap=200,    # Overlap between chunks
    separators=["\n\n", "\n", ". ", ", ", " "]  # Split priority
)

# Chunk plain text
chunks = chunk_text(text, config)

# Chunk RawData (preserves metadata)
from openbench.data.sources import PDFSource
raw_data = PDFSource("doc.pdf").extract()
chunks = chunk_raw_data(raw_data, config)  # Returns List[Chunk]
```

## PineconeStore

Vector store with semantic search:

```python
from openbench.data.stores import PineconeStore

# Initialize
store = PineconeStore(
    index_name="my-index",
    namespace="documents",
    embedding_model="text-embedding-3-small",  # OpenAI
    dimension=1536,  # Auto-detected if not specified
)

# Index chunks
store.index_chunks(chunks)

# Semantic search
results = store.search(
    query="What is the revenue?",
    top_k=5,
    filter={"source_type": "pdf"}
)

# Access results
for result in results:
    print(f"Score: {result.score}")
    print(f"Content: {result.content}")
    print(f"Metadata: {result.metadata}")
```

## Exception Handling

```python
from openbench.data.exceptions import (
    DataLayerError,      # Base exception
    SourceError,         # Data source errors
    ExtractionError,     # Extraction failed
    ValidationError,     # Validation failed
    FileNotFoundError,   # File not found
    UnsupportedFormatError,  # Format not supported
)

from openbench.data.stores import (
    StoreError,          # Base store error
    IndexNotFoundError,  # Index doesn't exist
    StoreConnectionError,  # Connection failed
    DimensionMismatchError,  # Vector dimension mismatch
    QuotaExceededError,  # API quota exceeded
    EmbeddingError,      # Embedding generation failed
    ItemNotFoundError,   # Item not in store
    InvalidQueryError,   # Query format invalid
)

# Usage
try:
    results = store.search(query)
except IndexNotFoundError:
    store.create_index()
except EmbeddingError as e:
    logger.error(f"Embedding failed: {e}")
```

## RAG Pattern

Retrieval-Augmented Generation workflow:

```python
from openbench.data.sources import PDFSource
from openbench.data.stores import PineconeStore, ChunkingConfig

# 1. Extract and chunk
source = PDFSource("documents/report.pdf")
raw_data = source.extract()
chunks = chunk_raw_data(raw_data, ChunkingConfig(chunk_size=500))

# 2. Index
store = PineconeStore(index_name="knowledge", namespace="reports")
store.index_chunks(chunks)

# 3. Retrieve
results = store.search(query="revenue 2024", top_k=5)

# 4. Build context
context = "\n\n".join([r.content for r in results])
```

## EmbeddingMixin

Add embedding capabilities to custom stores:

```python
from openbench.data.stores.base import EmbeddingMixin

class MyStore(EmbeddingMixin):
    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        self._embedding_model = embedding_model
        self._dimension = None  # Auto-detect

    def index(self, text: str):
        vector = self._embed(text)  # From mixin
        # Store vector...

    def index_batch(self, texts: list):
        vectors = self._embed_batch(texts, batch_size=100)
        # Store vectors...
```

## Hybrid Search

Combine vector similarity with BM25 keyword scoring for better retrieval. Implemented via `HybridSearchMixin` in `src/openbench/data/stores/base.py`.

```python
from openbench.data.stores.pinecone import PineconeStore

# Enable hybrid search on PineconeStore
store = PineconeStore(
    index_name="knowledge",
    namespace="documents",
    hybrid_search=True,       # Enable BM25 + vector reranking
    vector_weight=0.7,        # 0.7 vector + 0.3 BM25 keyword
)

# search() automatically applies hybrid reranking
results = store.search(Query(text="Q3 cloud revenue", limit=5))
```

### Standalone BM25 scoring

Use `HybridSearchMixin` directly for custom re-ranking:

```python
from openbench.data.stores.base import HybridSearchMixin

# BM25 score for a single document
score = HybridSearchMixin.bm25_score(
    query_terms=["cloud", "revenue"],
    document="Cloud division revenue reached $2.1B",
)

# Re-rank search results with hybrid scoring
reranked_items, reranked_scores = HybridSearchMixin.hybrid_rerank(
    items=items,              # List of dicts with "content" key
    scores=vector_scores,     # Vector similarity scores
    query="cloud revenue",
    vector_weight=0.7,
    keyword_weight=0.3,
)
```

### How it works

1. Vector similarity search via Pinecone API -> items + scores
2. BM25 keyword scoring per item (term frequency + length normalization)
3. Normalize both score sets to 0-1
4. Weighted combination: `hybrid = vector_weight * vector + keyword_weight * bm25`
5. Sort descending by hybrid score

BM25 is simplified (no corpus-level IDF) since we re-rank a small top-K result set, not the full corpus.

For examples, see `examples/stores/hybrid_search_demo.py`

## Anti-Patterns

**DO NOT:**
- Set `chunk_overlap >= chunk_size` - raises `ValueError` in `ChunkingConfig.__post_init__`
- Skip `_sanitize_metadata()` for Pinecone - only primitives and string lists allowed
- Catch all exceptions from store operations - use specific exceptions from `openbench.data.stores.exceptions`
- Forget namespace isolation - always use `ProjectContext` or explicit namespaces for multi-tenant
- Call `_embed()` directly on large datasets - use `_embed_batch()` with batch_size for efficiency
- Assume embedding dimension - use `EmbeddingMixin._get_dimension()` which auto-detects from provider

## Cross-References

- **Intelligence Layer**: `BaseAgent` uses `DataStore` for RAG retrieval → see `intelligence-layer` skill
- **Composing Workflows**: DataSources and stores used in `DataLayer` → see `composing-workflows` skill
- **Creating Abstractions**: `DataSource` and `DataStore` base classes → see `creating-abstractions` skill
- **Testing**: Mock store and embedding calls → see `testing-openbench` skill

## Best Practices

1. **Choose chunk size wisely** - 500-1000 chars for Q&A, larger for summarization
2. **Use namespaces** - Separate different document collections
3. **Include metadata** - Source, timestamp, page number for filtering
4. **Handle errors** - Wrap store operations in try/except with specific exception types
5. **Batch operations** - Use batch methods for large datasets

For examples, see `examples/stores/hybrid_search_demo.py` and `examples/workflows/research/hybrid_research_agent.py`
