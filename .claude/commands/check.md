---
name: check
description: Run all quality checks (lint + type check + tests)
argument-hint: "[options]"
---

# /check

Run all quality checks: formatting, linting, type checking, and tests for both Python and TypeScript.

## Usage

```
/check [options]
```

## Options

- `all` - Run everything (default)
- `quick` - Run lint only (skip type check and tests)
- `ci` - Run everything with coverage report
- `python` - Python checks only
- `ts` - TypeScript checks only

## Instructions

1. Parse the option provided (default: `all`)
2. Run checks sequentially, stopping on first failure:

### Python

```bash
# Step 1: Formatting check
black --check src/ tests/ examples/

# Step 2: Linting
ruff check src/ tests/

# Step 3: Type checking (skip for 'quick')
mypy src/openbench/

# Step 4: Tests (skip for 'quick')
python -m pytest tests/ -q

# For 'ci' option, use pytest with coverage instead:
pytest tests/ --cov=openbench --cov-report=term-missing
```

### TypeScript (studio/chat-ui/)

```bash
# Step 1: Lint + formatting check (biome via npx)
cd studio/chat-ui && npx @biomejs/biome check src/ tests/

# Step 2: Type checking (skip for 'quick')
cd studio/chat-ui && pnpm tsc --noEmit

# Step 3: Tests (skip for 'quick')
cd studio/chat-ui && pnpm vitest run
```

3. Run Python and TypeScript checks in parallel when both are selected
4. Report results summary:
   - List which checks passed/failed per language
   - For failures, show the relevant output
   - Suggest fixes for any issues found
