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

## Best Practices

1. **Choose chunk size wisely** - 500-1000 chars for Q&A, larger for summarization
2. **Use namespaces** - Separate different document collections
3. **Include metadata** - Source, timestamp, page number for filtering
4. **Handle errors** - Wrap store operations in try/except
5. **Batch operations** - Use batch methods for large datasets

For examples, see `examples/workflows/research/hybrid_research_agent.py`
