# OpenBench Architecture

---

## Overview

Three-layer architecture with composable abstractions for building AI workflows.

**Core Principles:**
1. Everything is Chainable
2. Composition Over Configuration
3. Implementation Independence
4. Two-Level Orchestration (L1 components, L2 systems)
5. DAG Workflows
6. Universal Control Plane (bring your own agents from LangChain, AG2, CrewAI, etc.)

---

## The Three-Layer Model

```
┌─────────────────────────────────────────────────────────┐
│                     OUTPUT LAYER                        │
│  Generate outputs in any format: PDF, PowerPoint,      │
│  Audio, Dashboards, Infographics                       │
│                                                         │
│  OutputGenerator abstraction                           │
│  Implementations: ReportLab, python-pptx, ElevenLabs   │
└─────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────┐
│                  INTELLIGENCE LAYER                     │
│  Execute AI tasks: Research, Analysis, Content         │
│  Multi-agent orchestration, tool use, memory           │
│                                                         │
│  Agent & LLMProvider abstractions                      │
│  Implementations: OpenAI, Anthropic, Local Models      │
└─────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────┐
│                      DATA LAYER                         │
│  Extract and index data from any source                │
│  Unified search across heterogeneous data              │
│                                                         │
│  DataSource & DataStore abstractions                   │
│  Implementations: PDF, YouTube, Pinecone, ChromaDB     │
└─────────────────────────────────────────────────────────┘
```

---

## Infrastructure

### Provider Service
Centralized provider management with credential encryption (Fernet), default provider per type, and persistence to `~/.openbench/providers.json`.

### Plugin Registry
Dynamic registration with decorators, auto-discovery, metadata support, and singleton patterns.

### Config
Single source of truth with dot-notation access, environment overrides, and LLM model registry. Persisted to `~/.openbench/config.json`.

---

## Security

Credentials encrypted at rest using Fernet. Key stored at `~/.openbench/.credentials_key` (0o600). Format: `enc:v1:<base64>`. Graceful fallback if `cryptography` not installed.

```bash
pip install openbench[security]
```

---

**See [API.md](API.md) for reference and [GETTING_STARTED.md](GETTING_STARTED.md) for quick start.**
