---
name: example
description: Run an OpenBench example workflow
argument-hint: "[name]"
disable-model-invocation: true
---

# /example

Run an OpenBench example workflow.

## Usage

```
/example [name]
```

## Available Examples

- `sustainability` - Complete sustainability report workflow (default)
- `abstractions` - Core abstractions demo
- `orchestration` - L1/L2 orchestration demo
- `adapters` - Framework adapters demo
- `gemini-agent` - BaseAgent + GeminiLLMProvider with tool calling (requires GOOGLE_API_KEY)
- `agentic-research` - BaseAgent + RAG + Web Search, 3 RAG approaches (requires GOOGLE_API_KEY)
- `agentic-analysis` - AnalysisAgent + StructuredOutputAgent, 3 analysis approaches (requires GOOGLE_API_KEY)
- `pdf-workflow` - PDF → Google ADK → PDF workflow (requires GOOGLE_API_KEY)
- `entity` - Entity extraction from documents (requires GOOGLE_API_KEY)
- `hybrid` - Hybrid research agent (RAG + LLM enrichment)

## Instructions

1. Parse the example name (default: `sustainability`)
2. Run the appropriate example:

```bash
# Sustainability report
python examples/workflows/reports/sustainability_report.py

# Core abstractions
python examples/core/core_abstractions_demo.py

# Orchestration demo
python examples/core/orchestration_demo.py

# Framework adapters
python examples/adapters/framework_adapters_demo.py

# Gemini agent with tool calling (requires GOOGLE_API_KEY)
python examples/intelligence/gemini_agent_demo.py

# Agentic research - BaseAgent + RAG + Web Search (requires GOOGLE_API_KEY)
python examples/intelligence/agentic_research_demo.py

# Agentic analysis - AnalysisAgent + StructuredOutputAgent (requires GOOGLE_API_KEY)
python examples/intelligence/agentic_analysis_demo.py

# PDF workflow (requires GOOGLE_API_KEY and input PDF)
python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.pdf

# Entity extraction (requires GOOGLE_API_KEY)
python examples/workflows/entity/entity_analysis_adk_workflow.py

# Hybrid research agent (requires GOOGLE_API_KEY and PINECONE_API_KEY)
python examples/workflows/research/hybrid_research_agent.py "your query" --mode hybrid --namespace knowledge-base
```

3. Show the output to the user
4. Explain what the example demonstrates
