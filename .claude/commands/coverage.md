---
name: coverage
description: Run tests with coverage report
argument-hint: "[module]"
disable-model-invocation: true
---

# /coverage

Run the test suite with coverage analysis.

## Usage

```
/coverage [module]
```

## Options

- (no argument) - Full coverage report for all modules
- `core` - Coverage for openbench.core only
- `intelligence` - Coverage for openbench.intelligence only
- `data` - Coverage for openbench.data only
- `adapters` - Coverage for openbench.adapters only
- `output` - Coverage for openbench.output only

## Instructions

1. Parse the module option (default: full coverage)
2. Run the appropriate pytest command:

```bash
# Full coverage
pytest tests/ --cov=openbench --cov-report=term-missing

# Module-specific coverage
pytest tests/ --cov=openbench.core --cov-report=term-missing
pytest tests/ --cov=openbench.intelligence --cov-report=term-missing
pytest tests/ --cov=openbench.data --cov-report=term-missing
pytest tests/ --cov=openbench.adapters --cov-report=term-missing
pytest tests/ --cov=openbench.output --cov-report=term-missing
```

3. Analyze the results:
   - Report overall coverage percentage
   - List modules below 80% coverage threshold
   - Identify untested files (0% coverage)
   - Suggest which tests to write next for maximum impact
