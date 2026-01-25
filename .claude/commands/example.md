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

## Instructions

1. Parse the example name (default: `sustainability`)
2. Run the appropriate example:

```bash
# Sustainability report
python examples/sustainability_report.py

# Core abstractions
python examples/core_abstractions_demo.py

# Orchestration demo
python examples/orchestration_demo.py
```

3. Show the output to the user
4. Explain what the example demonstrates
