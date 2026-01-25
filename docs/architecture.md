# OpenBench Architecture

**Vision and Design Philosophy**

---

## Overview

OpenBench is built on a **three-layer architecture** with **composable abstractions** that enable building complex AI workflows from simple, reusable components.

### Core Philosophy

1. **Everything is Chainable** - All components implement a unified interface
2. **Composition Over Configuration** - Build workflows by composing components
3. **Implementation Independence** - Swap providers without changing code
4. **Two-Level Orchestration** - Compose components (L1) into systems (L2)
5. **DAG Workflows** - Support complex directed acyclic graphs, not just sequences

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

**See [docs/API.md](API.md) for complete reference and [docs/GETTING_STARTED.md](GETTING_STARTED.md) for quick start.**

---

**OpenBench: World-class abstractions for building AI workflows**
