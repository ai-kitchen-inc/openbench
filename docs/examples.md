# Examples

The `examples/` directory contains small concept demos, workflow scripts, and full-stack applications.

## No-Key Examples

These are the best first checks after installation:

```bash
python examples/core/core_abstractions_demo.py
python examples/core/orchestration_demo.py
python examples/core/agent_registry_demo.py
python examples/adapters/framework_adapters_demo.py
python examples/workflows/reports/sustainability_report.py
```

## Examples Requiring Provider Keys

Some examples call external model, embedding, search, or vector services:

```bash
export GOOGLE_API_KEY=your-google-api-key
export PINECONE_API_KEY=your-pinecone-api-key

python examples/intelligence/gemini_agent_demo.py
python examples/embeddings/embedding_providers_demo.py
python examples/workflows/research/hybrid_research_agent.py "revenue 2024 acme" --mode rag
```

## Demo Launcher

The CLI can discover and run example applications:

```bash
openbench demo list
openbench demo run general-chat-OpenUI
```

The launcher detects Python scripts and server apps under `examples/`. Some demos install dependencies, start backend servers, or require environment variables.

## Open WebUI Chat Example

The migrated chat example combines the Python backend chat layer with Open WebUI:

- `examples/general-chat-OpenUI/`: general-purpose document-aware chat app with persona files, persistent sessions, and OpenAI-compatible `/v1` endpoints for Open WebUI.

Legacy React frontend examples still exist in `examples/`, but the bundled
`@openbench/chat-ui` SDK is excluded from the active framework UI path.
