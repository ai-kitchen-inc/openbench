---
name: testing-openbench
description: Writing tests for OpenBench components, workflows, and integrations. Use when writing unit tests, running test suite, creating test fixtures, or mocking components.
---

# Testing OpenBench

## Test File Conventions

```
Source file                     → Test file
src/openbench/core/foo.py      → tests/test_foo.py
src/openbench/data/sources/bar.py → tests/test_bar_source.py
src/openbench/intelligence/baz.py → tests/test_baz_agent.py
```

## Running Tests

```bash
# All tests
python -m unittest discover tests -v

# Specific test file
python -m unittest tests.test_abstractions -v

# With coverage
pytest tests/ --cov=openbench --cov-report=term-missing
```

## Testing DataSource

```python
import unittest
from openbench.core import RawData
from my_module import MyDataSource

class TestMyDataSource(unittest.TestCase):
    def setUp(self):
        self.source = MyDataSource(config="test")

    def test_source_type(self):
        self.assertEqual(self.source.source_type, "my-source")

    def test_extract(self):
        result = self.source.extract()
        self.assertIsInstance(result, RawData)
        self.assertIsNotNone(result.content)

    def test_chainable_invoke(self):
        result = self.source.invoke({})
        self.assertIsInstance(result, RawData)
```

## Testing Workflow Composition

```python
import unittest
from openbench.core import Chain, Parallel, Lambda

class TestWorkflowComposition(unittest.TestCase):
    def test_sequential_chain(self):
        add_one = Lambda(lambda x: x + 1)
        multiply_two = Lambda(lambda x: x * 2)

        chain = add_one | multiply_two
        result = chain.invoke(5)
        self.assertEqual(result, 12)  # (5 + 1) * 2

    def test_parallel_execution(self):
        add_one = Lambda(lambda x: x + 1)
        multiply_two = Lambda(lambda x: x * 2)

        parallel = add_one & multiply_two
        result = parallel.invoke(5)
        self.assertEqual(result, [6, 10])
```

## Testing with Mocks

```python
from unittest.mock import Mock, patch

class TestWithMocks(unittest.TestCase):
    def test_data_layer_with_mock_source(self):
        mock_source = Mock()
        mock_source.invoke.return_value = Mock(content="test data")

        layer = DataLayer(sources=mock_source, stores=[])
        result = layer.invoke({})

        mock_source.invoke.assert_called_once()

    @patch('my_module.external_api')
    def test_agent_with_patched_api(self, mock_api):
        mock_api.return_value = {"response": "test"}
        agent = MyAgent(goal="test")
        result = agent.execute(self.context)
        self.assertEqual(result.status, "completed")
```

## Requirements

- **Minimum coverage**: 80%
- **Happy path**: Normal successful scenarios
- **Edge cases**: Boundary conditions, empty inputs
- **Error handling**: Invalid inputs, exceptions

## Anti-Patterns

**DO NOT:**
- Write trivial tests that always pass (e.g., `assertTrue(validator.validate("hello"))` when validate always returns True)
- Mix mocking styles inconsistently - prefer `Mock*` classes for abstractions, `@patch` for external deps
- Test internal methods directly - test through public API (`invoke()`, `execute()`, `extract()`)
- Skip mocking LLM calls - real API calls make tests slow, flaky, and expensive
- Forget to test the Chainable interface - every component should test `invoke()` and `|` operator
- Use hardcoded test values without explanation - add comments for magic numbers

## Cross-References

- **Intelligence Layer**: Mock `LLMProvider.generate()` / `generate_stream()` and `ToolExecutor` → see `intelligence-layer` skill
- **Data Layer**: Mock store operations and embedding calls → see `data-layer` skill
- **Adapters**: Mock external framework imports with lazy import pattern → see `adapters` skill
- **Output Layer**: Mock file I/O for generator tests → see `output-layer` skill
- **Creating Abstractions**: Test abstract property implementations → see `creating-abstractions` skill

## Best Practices

1. One assertion per concept
2. Use descriptive test names: `test_extract_returns_raw_data`
3. Set up fixtures in `setUp()`
4. Clean up in `tearDown()`
5. Mock external dependencies
6. Test both success and failure paths
