---
name: testing-openbench
description: Writing tests for OpenBench components, workflows, and integrations
---

# Testing OpenBench Skill

This skill is auto-invoked when writing tests, running test suites, or working with test coverage.

## Triggers

- Writing unit tests
- Running test suite
- Creating test fixtures
- Mocking components
- Testing workflows
- Coverage analysis

## Test File Conventions

```
Source file                     → Test file
src/openbench/core/foo.py      → tests/test_foo.py
src/openbench/sources/bar.py   → tests/test_bar_source.py
src/openbench/agents/baz.py    → tests/test_baz_agent.py
src/openbench/outputs/qux.py   → tests/test_qux_generator.py
src/openbench/workflows/       → tests/test_workflow.py
```

## Running Tests

```bash
# Run all tests
python -m unittest discover tests -v

# Run specific test file
python -m unittest tests.test_abstractions -v

# Run specific test class
python -m unittest tests.test_abstractions.TestDataSource -v

# Run specific test method
python -m unittest tests.test_abstractions.TestDataSource.test_extract -v

# With pytest (if installed)
pytest tests/ -v
pytest tests/test_abstractions.py -v
pytest tests/ --cov=openbench --cov-report=term-missing
```

## Test Patterns

### Testing DataSource

```python
import unittest
from openbench.core import RawData
from my_module import MyDataSource


class TestMyDataSource(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.source = MyDataSource(config="test")

    def test_source_type(self):
        """Test source_type property."""
        self.assertEqual(self.source.source_type, "my-source")

    def test_source_id(self):
        """Test source_id property."""
        self.assertIn("my-source", self.source.source_id)

    def test_get_metadata(self):
        """Test metadata retrieval."""
        metadata = self.source.get_metadata()
        self.assertIsInstance(metadata, dict)
        self.assertIn("type", metadata)

    def test_validate_success(self):
        """Test successful validation."""
        self.assertTrue(self.source.validate())

    def test_validate_failure(self):
        """Test validation failure."""
        invalid_source = MyDataSource(config=None)
        self.assertFalse(invalid_source.validate())

    def test_extract(self):
        """Test data extraction."""
        result = self.source.extract()
        self.assertIsInstance(result, RawData)
        self.assertIsNotNone(result.content)
        self.assertEqual(result.source, self.source)

    def test_extract_content_type(self):
        """Test extracted content type."""
        result = self.source.extract()
        self.assertIn(result.content_type, ["text", "structured", "binary"])

    def test_chainable_invoke(self):
        """Test Chainable interface."""
        result = self.source.invoke({})
        self.assertIsInstance(result, RawData)
```

### Testing Agent

```python
import unittest
from openbench.core import ExecutionContext, ExecutionResult
from my_module import MyAgent


class TestMyAgent(unittest.TestCase):
    def setUp(self):
        self.agent = MyAgent(goal="test task")
        self.context = ExecutionContext(
            goal="test task",
            input_data={"key": "value"},
            history=[]
        )

    def test_agent_type(self):
        """Test agent_type property."""
        self.assertEqual(self.agent.agent_type, "my-agent")

    def test_execute_success(self):
        """Test successful execution."""
        result = self.agent.execute(self.context)
        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.status, "completed")

    def test_execute_output(self):
        """Test execution output."""
        result = self.agent.execute(self.context)
        self.assertIsNotNone(result.output)

    def test_execute_metadata(self):
        """Test execution metadata."""
        result = self.agent.execute(self.context)
        self.assertIsInstance(result.metadata, dict)

    def test_estimate_cost(self):
        """Test cost estimation."""
        cost = self.agent.estimate_cost(self.context)
        self.assertIsInstance(cost, float)
        self.assertGreaterEqual(cost, 0)

    def test_chainable_invoke(self):
        """Test Chainable interface."""
        result = self.agent.invoke(self.context)
        self.assertIsInstance(result, ExecutionResult)
```

### Testing Workflow Composition

```python
import unittest
from openbench.core import Chain, Parallel, Lambda


class TestWorkflowComposition(unittest.TestCase):
    def test_sequential_chain(self):
        """Test sequential composition."""
        add_one = Lambda(lambda x: x + 1)
        multiply_two = Lambda(lambda x: x * 2)

        chain = add_one | multiply_two
        result = chain.invoke(5)
        self.assertEqual(result, 12)  # (5 + 1) * 2

    def test_parallel_execution(self):
        """Test parallel composition."""
        add_one = Lambda(lambda x: x + 1)
        multiply_two = Lambda(lambda x: x * 2)

        parallel = add_one & multiply_two
        result = parallel.invoke(5)
        self.assertEqual(result, [6, 10])

    def test_complex_dag(self):
        """Test complex DAG structure."""
        step_a = Lambda(lambda x: x + 1)
        step_b = Lambda(lambda x: x * 2)
        step_c = Lambda(lambda x: x - 1)
        step_d = Lambda(lambda x: sum(x))

        # A → (B & C) → D
        workflow = step_a | Parallel([step_b, step_c]) | step_d
        result = workflow.invoke(5)
        # (5+1) → [12, 5] → 17
        self.assertEqual(result, 17)
```

### Testing with Mocks

```python
import unittest
from unittest.mock import Mock, patch, MagicMock
from openbench.core import DataLayer, IntelligenceLayer


class TestWithMocks(unittest.TestCase):
    def test_data_layer_with_mock_source(self):
        """Test DataLayer with mocked source."""
        mock_source = Mock()
        mock_source.invoke.return_value = Mock(content="test data")

        layer = DataLayer(sources=mock_source, stores=[])
        result = layer.invoke({})

        mock_source.invoke.assert_called_once()
        self.assertIn("raw_data", result)

    @patch('my_module.external_api')
    def test_agent_with_patched_api(self, mock_api):
        """Test agent with patched external API."""
        mock_api.return_value = {"response": "test"}

        agent = MyAgent(goal="test")
        result = agent.execute(self.context)

        mock_api.assert_called_once()
        self.assertEqual(result.status, "completed")
```

### Testing Workflows

```python
import unittest
import tempfile
import shutil
from openbench.workflows import Workflow
from openbench.core import LocalStateStore, Lambda


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_store = LocalStateStore(base_path=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_workflow_execution(self):
        """Test basic workflow execution."""
        chain = Lambda(lambda x: x * 2)
        workflow = Workflow(
            name="test-workflow",
            chain=chain,
            state_store=self.state_store,
            checkpoints=True
        )

        result = workflow.run(5)
        self.assertEqual(result, 10)

    def test_workflow_checkpointing(self):
        """Test workflow creates checkpoints."""
        chain = Lambda(lambda x: x * 2)
        workflow = Workflow(
            name="test-workflow",
            chain=chain,
            state_store=self.state_store,
            checkpoints=True
        )

        workflow.run(5)

        # Verify state was saved
        states = self.state_store.list_workflows()
        self.assertEqual(len(states), 1)
```

## Test Coverage Requirements

- **Minimum coverage**: 80%
- **Happy path**: Normal successful scenarios
- **Edge cases**: Boundary conditions, empty inputs
- **Error handling**: Invalid inputs, exceptions

## Best Practices

1. **One assertion per concept** - Keep tests focused
2. **Use descriptive names** - `test_extract_returns_raw_data`
3. **Set up fixtures in setUp()** - Avoid repetition
4. **Clean up in tearDown()** - Remove temp files
5. **Mock external dependencies** - Isolate unit tests
6. **Test both success and failure** - Cover error paths
7. **Document test purpose** - Use docstrings

## Common Fixtures

```python
class BaseTestCase(unittest.TestCase):
    """Base test case with common fixtures."""

    def create_mock_source(self, content="test"):
        mock = Mock(spec=DataSource)
        mock.extract.return_value = RawData(
            content=content,
            content_type="text",
            metadata={},
            source=mock
        )
        return mock

    def create_mock_agent(self, output=None):
        mock = Mock(spec=Agent)
        mock.execute.return_value = ExecutionResult(
            output=output or {},
            status="completed",
            metadata={},
            cost=0.0,
            tokens_used=0
        )
        return mock

    def create_execution_context(self, goal="test", input_data=None):
        return ExecutionContext(
            goal=goal,
            input_data=input_data or {},
            history=[]
        )
```
