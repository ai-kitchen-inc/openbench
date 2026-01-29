# /test

Run the OpenBench test suite.

## Usage

```
/test [options]
```

## Options

- `all` - Run all tests (default)
- `abstractions` - Run abstraction tests only
- `chainable` - Run chainable composition tests only
- `layers` - Run L2 layer tests only
- `workflow` - Run workflow tests only
- `google_adk` - Run Google ADK adapter tests only
- `pdf_generator` - Run PDF generator tests only
- `e2e` - Run E2E workflow tests only
- `coverage` - Run with coverage report

## Instructions

1. Parse the option provided (default: `all`)
2. Run the appropriate test command:

```bash
# All tests
python -m unittest discover tests -v

# Specific test file
python -m unittest tests.test_abstractions -v
python -m unittest tests.test_chainable -v
python -m unittest tests.test_layers -v
python -m unittest tests.test_workflow -v
python -m unittest tests.test_google_adk_adapter -v
python -m unittest tests.test_pdf_generator -v
python -m unittest tests.test_pdf_workflow_e2e -v

# With coverage (requires pytest-cov)
pytest tests/ --cov=openbench --cov-report=term-missing
```

3. Report the results to the user
4. If tests fail, analyze the failures and suggest fixes
