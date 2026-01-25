# OpenBench Test Suite

Comprehensive unit tests for OpenBench core functionality.

## Test Coverage

### Core Abstractions (`test_abstractions.py`)
Tests for abstract base classes and interfaces:
- ✅ DataSource interface and Chainable behavior
- ✅ DataStore interface (index, search, get, update, delete)
- ✅ Agent interface and Chainable behavior
- ✅ LLMProvider interface
- ✅ Tool interface
- ✅ OutputGenerator interface and Chainable behavior
- ✅ RawData, Query, SearchResult containers
- ✅ ExecutionContext, ExecutionResult
- ✅ GeneratedOutput serialization/deserialization

### Registry Pattern (`test_registry.py`)
Tests for provider registration and factory pattern:
- ✅ DataSourceRegistry
- ✅ DataStoreRegistry
- ✅ AgentRegistry
- ✅ LLMProviderRegistry
- ✅ ToolRegistry
- ✅ OutputGeneratorRegistry
- ✅ Bulk registration with `register_all()`
- ✅ Error handling (unknown types/providers)
- ✅ Registry isolation
- ✅ Multiple providers per type

### Chainable Composition (`test_chainable.py`)
Tests for DAG workflow composition:
- ✅ Pipe operator (`|`) creates Chain
- ✅ And operator (`&`) creates Parallel
- ✅ Sequential execution (Chain)
- ✅ Parallel execution (Parallel)
- ✅ Conditional branching
- ✅ Router (multi-way routing)
- ✅ Lambda wrappers
- ✅ Passthrough
- ✅ Complex DAG compositions
- ✅ Batch processing
- ✅ Config passthrough

### L2 Layers (`test_layers.py`)
Tests for system-level orchestration:
- ✅ DataLayer creation and invocation
- ✅ IntelligenceLayer creation and invocation
- ✅ OutputLayer creation and invocation
- ✅ Layer composition (DataLayer | IntelligenceLayer | OutputLayer)
- ✅ Complex L1 + L2 compositions
- ✅ `create_workflow()` helper function

### Workflow (`test_workflow.py`)
Tests for named, stateful workflows:
- ✅ Workflow creation
- ✅ Workflow execution (`run()`)
- ✅ Metadata support
- ✅ Sequential workflows
- ✅ Checkpointing enabled/disabled
- ✅ Default state store
- ✅ Complex DAG workflows
- ✅ Conditional workflows
- ✅ Router workflows
- ✅ String representation

## Running Tests

### Run all tests
```bash
python -m unittest discover tests
```

### Run specific test file
```bash
python -m unittest tests.test_abstractions
python -m unittest tests.test_registry
python -m unittest tests.test_chainable
python -m unittest tests.test_layers
python -m unittest tests.test_workflow
```

### Run specific test class
```bash
python -m unittest tests.test_abstractions.TestAbstractions
```

### Run specific test method
```bash
python -m unittest tests.test_abstractions.TestAbstractions.test_data_source_interface
```

### Run with verbose output
```bash
python -m unittest discover tests -v
```

## Test Organization

```
tests/
├── __init__.py                 # Test package marker
├── README.md                   # This file
├── test_abstractions.py        # Core abstraction tests
├── test_registry.py            # Registry pattern tests
├── test_chainable.py           # Chainable composition tests
├── test_layers.py              # L2 layer tests
└── test_workflow.py            # Workflow tests
```

## Adding New Tests

When adding new functionality:

1. **Add test file**: `tests/test_<module>.py`
2. **Import unittest**: `import unittest`
3. **Create test class**: `class Test<Feature>(unittest.TestCase)`
4. **Add test methods**: Methods starting with `test_`
5. **Run tests**: Ensure all tests pass

Example:
```python
import unittest
from openbench.core import MyNewFeature

class TestMyNewFeature(unittest.TestCase):
    """Tests for MyNewFeature."""

    def test_basic_functionality(self):
        """Test basic functionality."""
        feature = MyNewFeature()
        result = feature.do_something()
        self.assertEqual(result, "expected")

if __name__ == "__main__":
    unittest.main()
```

## Test Principles

### 1. Test Behavior, Not Implementation
Focus on the public API and contract, not internal implementation details.

### 2. Use Mock Implementations
Create minimal mock implementations for testing:
- Simple, focused on the interface
- Don't test external dependencies

### 3. Test Edge Cases
Cover:
- Normal cases
- Edge cases (empty input, None, etc.)
- Error cases (invalid input, failures)

### 4. Keep Tests Independent
Each test should:
- Set up its own fixtures
- Not depend on other tests
- Clean up after itself

### 5. Use Descriptive Names
Test names should describe what they test:
- ✅ `test_data_source_chainable`
- ✅ `test_unknown_provider_raises_error`
- ❌ `test_1`, `test_foo`

## Continuous Integration

Tests should be run:
- Before every commit
- In CI/CD pipeline
- Before releases

## Test Coverage

Current coverage: **Comprehensive**

All core functionality is tested:
- ✅ Core abstractions
- ✅ Registry pattern
- ✅ Chainable composition
- ✅ L2 layers
- ✅ Workflows

## Contributing

When contributing:
1. Write tests for new features
2. Ensure all tests pass
3. Maintain test coverage
4. Follow test principles

## Questions?

See:
- [Main README](../README.md)
- [Documentation](../docs/README.md)
- [Examples](../examples/)
