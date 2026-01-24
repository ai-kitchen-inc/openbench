# Data Layer Architecture

## Overview

The Data Layer is the foundation of OpenBench, providing universal access to heterogeneous data sources through a unified interface. It handles everything from document processing to real-time API integration.

## Core Components

### 1. Data Source Connectors

#### Document Connectors

**Supported Formats:**
- PDF (with OCR support)
- Microsoft Office (Word, Excel, PowerPoint)
- Images (JPEG, PNG, TIFF with OCR)
- Plain text and Markdown
- HTML and Web pages

**Processing Pipeline:**
```
Raw Document → Extraction → Chunking → Metadata → Indexing
```

**Example Configuration:**
```python
from openbench.data import DocumentConnector

connector = DocumentConnector(
    source_path="./documents",
    ocr_enabled=True,
    chunk_size=512,
    chunk_overlap=50,
    metadata_extractors=["title", "author", "date", "entities"]
)

documents = connector.process()
```

#### Structured Data Connectors

**Supported Sources:**
- PostgreSQL, MySQL, SQL Server
- CSV, JSON, Parquet, Arrow
- NoSQL (MongoDB, DynamoDB)
- Data Warehouses (Snowflake, BigQuery, Redshift)

**Example:**
```python
from openbench.data import SQLConnector

connector = SQLConnector(
    connection_string="postgresql://user:pass@host:5432/db",
    tables=["customers", "orders", "products"],
    auto_index=True
)

# Natural language query
results = connector.query("Show me top 10 customers by revenue")
```

#### Multimedia Connectors

**Video Processing:**
- Automatic transcription
- Scene detection
- Caption generation
- Thumbnail extraction

**Audio Processing:**
- Speech-to-text
- Speaker diarization
- Audio fingerprinting

**Example:**
```python
from openbench.data import VideoConnector

connector = VideoConnector(
    source="https://youtube.com/watch?v=example",
    extract_audio=True,
    generate_captions=True,
    scene_threshold=0.3
)

indexed_video = connector.process()
# Query: "Find mentions of 'quarterly results' in the video"
```

#### API Connectors

**Supported Protocols:**
- REST APIs
- GraphQL
- WebSockets
- Webhooks
- Model Context Protocol (MCP)

**Example:**
```python
from openbench.data import APIConnector

connector = APIConnector(
    base_url="https://api.example.com",
    auth={"type": "bearer", "token": "..."},
    endpoints=[
        {"path": "/users", "method": "GET"},
        {"path": "/analytics", "method": "POST"}
    ],
    cache_ttl=300  # 5 minutes
)
```

### 2. Processing Pipeline

#### Text Extraction

**Techniques:**
- Native text extraction for digital documents
- OCR for scanned documents (Tesseract, Azure OCR)
- Layout analysis for complex documents
- Table extraction and structuring

#### Chunking Strategies

```python
from openbench.data.chunking import (
    FixedSizeChunker,
    SemanticChunker,
    RecursiveChunker
)

# Fixed size
chunker = FixedSizeChunker(size=512, overlap=50)

# Semantic (respects sentence/paragraph boundaries)
chunker = SemanticChunker(
    max_size=1000,
    respect_boundaries=["paragraph", "sentence"]
)

# Recursive (hierarchical chunking)
chunker = RecursiveChunker(
    levels=["document", "section", "paragraph"],
    max_size_per_level=[10000, 2000, 500]
)
```

#### Metadata Extraction

**Automatic Extraction:**
- Document properties (title, author, date)
- Named entities (people, organizations, locations)
- Keywords and topics
- Language detection
- Sentiment analysis

**Custom Metadata:**
```python
from openbench.data.metadata import MetadataExtractor

extractor = MetadataExtractor(
    extractors=[
        "entities",
        "keywords",
        "sentiment",
        "language"
    ],
    custom_extractors=[
        {
            "name": "department",
            "type": "regex",
            "pattern": r"Department:\s*(\w+)"
        }
    ]
)
```

### 3. Indexing & Search

#### Vector Search

**Embedding Models:**
- OpenAI Ada-002
- Sentence-Transformers
- Cohere Embed
- Custom fine-tuned models

**Vector Databases:**
- Pinecone
- Weaviate
- ChromaDB
- FAISS (local)

**Example:**
```python
from openbench.data.vector import VectorStore

store = VectorStore(
    provider="pinecone",
    index_name="documents",
    embedding_model="openai/text-embedding-ada-002",
    dimensions=1536
)

# Index documents
store.index(documents)

# Semantic search
results = store.search(
    query="What are the main risks in Q4?",
    top_k=10,
    filters={"year": 2024, "type": "quarterly_report"}
)
```

#### Full-Text Search

**Engines:**
- Elasticsearch
- Meilisearch
- Typesense

**Features:**
- Fuzzy matching
- Typo tolerance
- Phrase search
- Boolean operators
- Faceted search

**Example:**
```python
from openbench.data.search import FullTextSearch

search = FullTextSearch(
    provider="elasticsearch",
    index="documents"
)

results = search.query(
    query="revenue growth",
    filters={"year": 2024},
    facets=["department", "document_type"],
    typo_tolerance=True
)
```

#### Hybrid Search

Combines vector and keyword search for best results.

```python
from openbench.data.search import HybridSearch

search = HybridSearch(
    vector_weight=0.7,
    keyword_weight=0.3,
    rerank=True
)

results = search.query(
    query="customer satisfaction metrics",
    top_k=20
)
```

#### SQL Query Interface

**Natural Language to SQL:**
```python
from openbench.data.sql import NLQueryEngine

engine = NLQueryEngine(
    connection="postgresql://...",
    schema_path="./schema.json"
)

# Natural language query
df = engine.query(
    "Show me monthly revenue by product category for 2024"
)
```

### 4. Caching Layer

**Multi-Tier Caching:**

```
┌─────────────────────────────────────────┐
│          Request                         │
└───────────────┬─────────────────────────┘
                │
                ▼
        ┌───────────────┐
        │  L1: Memory   │  (milliseconds)
        │  (LRU Cache)  │
        └───────┬───────┘
                │ miss
                ▼
        ┌───────────────┐
        │  L2: Redis    │  (< 10ms)
        │  (Distributed)│
        └───────┬───────┘
                │ miss
                ▼
        ┌───────────────┐
        │  L3: Database │  (10-100ms)
        │  (Source)     │
        └───────────────┘
```

**Configuration:**
```python
from openbench.data.cache import CacheManager

cache = CacheManager(
    l1_size=1000,  # In-memory entries
    l2_ttl=3600,   # Redis TTL (seconds)
    invalidation_strategy="TTL"  # or "LRU", "Event-based"
)
```

### 5. Unified Data Access Interface (UDAI)

#### REST API

```bash
# Search across all data sources
POST /api/v1/data/search
{
  "query": "customer feedback on product X",
  "sources": ["documents", "databases", "apis"],
  "filters": {
    "date_range": "last_90_days"
  },
  "limit": 50
}

# Response
{
  "results": [
    {
      "source": "documents/reviews.pdf",
      "content": "...",
      "metadata": {...},
      "relevance_score": 0.92
    }
  ],
  "total": 847,
  "took_ms": 234
}
```

#### Model Context Protocol (MCP)

```python
from openbench.mcp import MCPServer

server = MCPServer(port=5000)

@server.tool("semantic_search")
def semantic_search(query: str, top_k: int = 10):
    """Search documents using semantic similarity."""
    return vector_store.search(query, top_k=top_k)

@server.tool("sql_query")
def sql_query(natural_language_query: str):
    """Execute SQL query from natural language."""
    return nl_query_engine.query(natural_language_query)

server.start()
```

#### Python SDK

```python
from openbench import DataLayer

# Initialize
data = DataLayer(
    api_key="...",
    endpoint="http://localhost:8000"
)

# Unified search across all sources
results = data.search(
    query="market trends in renewable energy",
    sources=["all"],  # or specific: ["pdfs", "sql", "web"]
    date_range="2024-01-01/2024-12-31"
)

# Direct SQL access
df = data.sql("SELECT * FROM customers WHERE revenue > 100000")

# Vector search
docs = data.vector_search(
    query="product complaints",
    filters={"category": "electronics"}
)
```

## Data Source Plugins

### Creating Custom Connectors

```python
from openbench.data.base import BaseConnector

class CustomAPIConnector(BaseConnector):
    """Connect to custom API and index data."""

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key

    def fetch(self) -> List[Dict]:
        """Fetch data from API."""
        # Implementation
        pass

    def transform(self, raw_data: List[Dict]) -> List[Document]:
        """Transform API data to Document format."""
        # Implementation
        pass

    def index(self, documents: List[Document]):
        """Index documents for search."""
        # Implementation
        pass

# Register connector
from openbench.data import register_connector
register_connector("custom_api", CustomAPIConnector)
```

## Performance Optimization

### Indexing Strategies

**Batch Indexing:**
```python
# Process large datasets in batches
connector.index_batch(
    documents,
    batch_size=1000,
    parallel=True,
    workers=4
)
```

**Incremental Updates:**
```python
# Only index changed documents
connector.index_incremental(
    source_path="./documents",
    since="2024-01-01",
    delete_removed=True
)
```

### Query Optimization

**Query Planning:**
- Automatically route queries to most efficient source
- Combine multiple data sources optimally
- Cache frequently accessed data

**Example:**
```python
from openbench.data.optimizer import QueryOptimizer

optimizer = QueryOptimizer(
    enable_cache=True,
    query_rewriting=True,
    parallel_execution=True
)

# Optimizer selects best strategy
results = optimizer.execute(
    query="Find all mentions of 'supply chain' in 2024",
    available_sources=["vector_db", "elasticsearch", "sql"]
)
```

## Security & Privacy

### Data Encryption

**At Rest:**
- AES-256 encryption for stored data
- Encrypted vector indices
- Secure credential storage (Vault)

**In Transit:**
- TLS 1.3 for all API calls
- Encrypted database connections

### Access Control

```python
from openbench.data.security import AccessControl

acl = AccessControl(
    policy="rbac",  # Role-Based Access Control
    rules=[
        {
            "role": "analyst",
            "resources": ["public_docs", "shared_dbs"],
            "permissions": ["read"]
        },
        {
            "role": "admin",
            "resources": ["*"],
            "permissions": ["read", "write", "delete"]
        }
    ]
)
```

### Data Masking

```python
from openbench.data.privacy import DataMasker

masker = DataMasker(
    rules=[
        {"field": "email", "method": "hash"},
        {"field": "ssn", "method": "redact"},
        {"field": "name", "method": "pseudonymize"}
    ]
)

# Automatically mask sensitive data in results
masked_results = masker.apply(results)
```

## Monitoring & Debugging

### Metrics

```python
# Available metrics
- data.connector.requests.total
- data.connector.requests.latency
- data.index.size
- data.cache.hit_ratio
- data.query.latency.p95
```

### Logging

```python
import logging
from openbench.data import DataLayer

logging.basicConfig(level=logging.DEBUG)

data = DataLayer(
    log_level="DEBUG",
    log_queries=True,
    log_slow_queries_threshold=1000  # ms
)
```

## Best Practices

1. **Choose the Right Connector**: Match connector to data source characteristics
2. **Optimize Chunk Size**: Balance between context and performance
3. **Use Hybrid Search**: Combine vector and keyword search for best results
4. **Enable Caching**: Dramatically improves repeated query performance
5. **Monitor Index Size**: Keep vector indices manageable (<10M documents per index)
6. **Incremental Updates**: Don't re-index everything for small changes
7. **Validate Data Quality**: Clean and validate data before indexing

## Troubleshooting

### Common Issues

**Slow Queries:**
- Check cache hit ratio
- Review query plan
- Consider adding filters
- Optimize chunk size

**Out of Memory:**
- Reduce batch size
- Use streaming for large datasets
- Increase cache TTL to reduce reprocessing

**Poor Search Quality:**
- Try hybrid search
- Adjust embedding model
- Improve chunking strategy
- Add metadata filters

---

**Next:** [Intelligence Layer](./intelligence-layer.md)
