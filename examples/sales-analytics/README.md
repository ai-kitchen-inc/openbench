# Sales Analytics

SDK skills demo — proves OpenBench works for any tabular data domain without project-specific tooling.

## Quick Start

```bash
openbench demo run sales-analytics
```

Or manually:

```bash
# Backend
cd examples/sales-analytics
pip install -e .
python server.py              # :8005

# Frontend
cd frontend
pnpm install && pnpm dev      # :5173
```

## What It Proves

- **Zero domain config** — no aliases.yaml, no units.yaml, no domain rules
- **SDK skills only** — data-context-extractor, query-explorer, data-visualization, export-excel, web-search
- **Column profiling** — LLM maps columns on first encounter, cached for repeat access
- **Same @openbench/chat-ui** — identical React SDK as lci-mini

## Try

1. Upload a CSV or Excel file with sales data
2. Ask: "What are the top regions by revenue?"
3. Ask: "Show a bar chart of sales by product"
4. Ask: "Export the summary to Excel"
5. Ask: "Search online for SaaS industry benchmarks 2026"
