---
name: lint
description: Run code formatting and linting
argument-hint: "[options]"
disable-model-invocation: true
---

# /lint

Run code formatting and linting.

## Usage

```
/lint [options]
```

## Options

- `check` - Check only, don't modify files (default)
- `fix` - Auto-fix issues where possible
- `src` - Lint source code only
- `tests` - Lint tests only

## Instructions

1. Parse the option provided (default: `check`)
2. Run the appropriate commands:

```bash
# Check formatting (black)
black --check src/ tests/ examples/

# Fix formatting
black src/ tests/ examples/

# Check linting (ruff)
ruff check src/ tests/

# Fix linting
ruff check --fix src/ tests/

# Type checking (mypy)
mypy src/openbench/
```

3. Report results to the user
4. If issues found with `check`, list them and ask if user wants to auto-fix
