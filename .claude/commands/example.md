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
- `pdf-workflow` - PDF → Google ADK → PDF workflow (requires GOOGLE_API_KEY)

## Instructions

1. Parse the example name (default: `sustainability`)
2. Run the appropriate example:

```bash
# Sustainability report
python examples/workflows/sustainability_report.py

# Core abstractions
python examples/core/core_abstractions_demo.py

# Orchestration demo
python examples/core/orchestration_demo.py

# Framework adapters
python examples/adapters/framework_adapters_demo.py

# PDF workflow (requires GOOGLE_API_KEY and input PDF)
python examples/workflows/pdf_google_adk_workflow.py input.pdf output.pdf
```

3. Show the output to the user
4. Explain what the example demonstrates
