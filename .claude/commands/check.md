---
name: check
description: Run all quality checks (lint + type check + tests)
argument-hint: "[options]"
disable-model-invocation: true
---

# /check

Run all quality checks: formatting, linting, type checking, and tests.

## Usage

```
/check [options]
```

## Options

- `all` - Run everything: black, ruff, mypy, tests (default)
- `quick` - Run black + ruff only (skip mypy and tests)
- `ci` - Run everything with coverage report

## Instructions

1. Parse the option provided (default: `all`)
2. Run checks sequentially, stopping on first failure:

```bash
# Step 1: Formatting check
black --check src/ tests/ examples/

# Step 2: Linting
ruff check src/ tests/

# Step 3: Type checking (skip for 'quick')
mypy src/openbench/

# Step 4: Tests (skip for 'quick')
python -m unittest discover tests -v

# For 'ci' option, use pytest with coverage instead:
pytest tests/ --cov=openbench --cov-report=term-missing
```

3. Report results summary:
   - List which checks passed/failed
   - For failures, show the relevant output
   - Suggest fixes for any issues found
