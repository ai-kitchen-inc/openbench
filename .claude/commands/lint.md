---
name: lint
description: Run code formatting and linting
argument-hint: "[options]"
---

# /lint

Run code formatting and linting for both Python and TypeScript.

## Usage

```
/lint [options]
```

## Options

- `check` - Check only, don't modify files (default)
- `fix` - Auto-fix issues where possible
- `python` - Lint Python only
- `ts` - Lint TypeScript only
- `src` - Lint source code only
- `tests` - Lint tests only

Options can be combined: `/lint fix python`, `/lint check ts`

## Instructions

1. Parse the options provided (default: `check` for both Python and TypeScript)
2. Run the appropriate commands based on options:

### Python (src/openbench/, tests/, examples/)

```bash
# Check formatting (black)
black --check src/ tests/ examples/

# Fix formatting
black src/ tests/ examples/

# Check linting (ruff)
ruff check src/ tests/

# Fix linting
ruff check --fix src/ tests/

# Type checking (mypy) -- only on check
mypy src/openbench/
```

### TypeScript (packages/chat-ui/)

```bash
# Check linting + formatting (biome via npx)
cd packages/chat-ui && npx @biomejs/biome check src/ tests/

# Fix linting + formatting
cd packages/chat-ui && npx @biomejs/biome check --write src/ tests/

# Type checking (tsc) -- only on check
cd packages/chat-ui && pnpm tsc --noEmit
```

3. Run Python and TypeScript checks in parallel when both are selected
4. Report results to the user with summary per language
5. If issues found with `check`, list them and ask if user wants to auto-fix
