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
openbench demo run general-chat
```

The launcher detects Python scripts and frontend projects under `examples/`. Some demos install frontend dependencies, start backend servers, or require environment variables.

## Chat UI Examples

The chat examples combine the Python backend chat layer with the React SDK:

- `examples/chat/`: AG-UI backend plus React frontend.
- `examples/general-chat/`: general-purpose chat app with persona files and persistent sessions.
- `examples/lci-mini/`: LCA-focused app with domain skills and Firebase/Drive integrations.
- `examples/sales-analytics/`: sales analytics chat app.

See `examples/README.md` and the README in each example directory for exact commands.
