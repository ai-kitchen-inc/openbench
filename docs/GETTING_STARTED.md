# Getting Started with OpenBench

Complete guide to install, test, and build your first OpenBench workflow.

---

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/ai-kitchen-inc/openbench.git
cd openbench

# Install
pip install -e .

# Verify
python -c "from openbench.core import Workflow; print('✓ OpenBench installed')"
```

### With Development Dependencies

```bash
# Install with testing and dev tools
pip install -e ".[dev]"
```

---

## Quick Test (30 seconds)

Verify everything works:

```bash
# Run the test suite
python -m unittest discover tests -v

# Should see:
# Ran 77 tests in X.XXXs
# OK
```

---

## Your First Workflow (5 minutes)

### Understanding the Abstractions

OpenBench provides world-class abstractions for building AI workflows:

**Core Components (L1):**
- `DataSource` - Extract data from any source
- `Agent` - Execute AI tasks
- `OutputGenerator` - Generate outputs in any format

**System Layers (L2):**
- `DataLayer` - Orchestrate data sources and stores
- `IntelligenceLayer` - Orchestrate AI agents
- `OutputLayer` - Orchestrate output generation

**Composition:**
- `|` (pipe) - Sequential: A → B → C
- `&` (and) - Parallel: [A, B, C] concurrently
- `Parallel([...])` - Explicit parallel composition
- `Workflow` - Named, stateful workflows with checkpointing

### Quick Example

```python
from openbench.core import (
    DataLayer, IntelligenceLayer, OutputLayer,
    Parallel
)

# Create layers
data_layer = DataLayer(sources=my_source)
intelligence_layer = IntelligenceLayer(agents=my_agent)
output_layer = OutputLayer(generators=my_generator)

# Compose into end-to-end workflow
workflow = data_layer | intelligence_layer | output_layer

# Execute
result = workflow.invoke({"query": "analyze sustainability"})
```

---

## Run the Examples

OpenBench includes three production-ready examples:

### 1. Core Abstractions Demo

Shows the foundational abstractions:

```bash
python examples/core_abstractions_demo.py
```

**Demonstrates:**
- Custom DataSource, Agent, and OutputGenerator
- Registry pattern for provider selection
- Sequential workflows (A | B | C)
- Parallel workflows (A & B & C)
- Conditional branching
- State management and checkpointing

### 2. L1/L2 Orchestration Demo

Shows two-level composition:

```bash
python examples/l1_l2_orchestration_demo.py
```

**Demonstrates:**
- L1 composition (components): `source1 | source2`
- L2 composition (layers): `DataLayer | IntelligenceLayer | OutputLayer`
- Complex DAGs: `(video1 | video2 | video3) & dict & table`
- End-to-end workflow execution

### 3. Sustainability Report (Real-World)

Complete workflow example:

```bash
python examples/sustainability_report.py
```

**Demonstrates:**
- Parallel data extraction from multiple sources
- Sequential multi-agent processing
- Parallel output generation (PDF & PowerPoint)
- State management with checkpointing
- Complete E2E workflow

---

## Core Concepts

### 1. Everything is Chainable

All components implement the `Chainable` interface:

```python
class Chainable(ABC):
    def invoke(self, input, config=None):
        """Execute this component"""
        pass
```

This allows composition using operators:

```python
# Sequential
workflow = step_a | step_b | step_c

# Parallel
workflow = Parallel([step_a, step_b, step_c])

# Combined
workflow = step_a | Parallel([step_b, step_c]) | step_d
```

### 2. L1 vs L2 Composition

**L1 (Component-level):**
```python
# Compose individual components
sources = source1 | source2 | source3
agents = agent1 | agent2
outputs = Parallel([pdf, pptx])
```

**L2 (System-level):**
```python
# Compose into layers
data_layer = DataLayer(sources=sources)
intelligence_layer = IntelligenceLayer(agents=agents)
output_layer = OutputLayer(generators=outputs)

# Then compose layers
workflow = data_layer | intelligence_layer | output_layer
```

### 3. Registry Pattern

Implementations are registered and created via factories:

```python
# Register your implementation
from openbench.core import DataSourceRegistry

DataSourceRegistry.register('pdf', 'custom', MyPDFSource)

# Create via registry
source = DataSourceRegistry.create('pdf', 'custom', path='./docs')
```

This allows swapping implementations without changing code.

### 4. Named Workflows with State

```python
from openbench.workflows import Workflow
from openbench.core import LocalStateStore

# Create named workflow with checkpointing
workflow = Workflow(
    name="sustainability-report",
    chain=data_layer | intelligence_layer | output_layer,
    state_store=LocalStateStore(base_path="./workflow_state"),
    checkpoints=True
)

# Execute (automatically checkpointed)
result = workflow.run({"project": "ESG Analysis"})
```

---

## Build Your Own

### Step 1: Create Custom Components

```python
from openbench.core import DataSource, RawData

class MyDataSource(DataSource):
    @property
    def source_type(self) -> str:
        return "custom"

    @property
    def source_id(self) -> str:
        return "my-source"

    def get_metadata(self):
        return {"name": "My Source"}

    def extract(self) -> RawData:
        # Your extraction logic
        return RawData(
            content="extracted data",
            content_type="text",
            metadata={},
            source=self
        )

    def validate(self) -> bool:
        return True
```

### Step 2: Compose Workflow

```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer

# Create your components
my_source = MyDataSource()
my_agent = MyAgent()
my_generator = MyGenerator()

# Compose into workflow
workflow = (
    DataLayer(sources=my_source)
    | IntelligenceLayer(agents=my_agent)
    | OutputLayer(generators=my_generator)
)

# Execute
result = workflow.invoke({})
```

### Step 3: Register for Reuse

```python
from openbench.core import DataSourceRegistry

# Register your component
DataSourceRegistry.register('custom', 'my-impl', MyDataSource)

# Now others can use it
source = DataSourceRegistry.create('custom', 'my-impl')
```

---

## Testing Your Work

### Run Unit Tests

```bash
# Run all tests
python -m unittest discover tests -v

# Run specific test file
python -m unittest tests.test_abstractions -v
python -m unittest tests.test_chainable -v
python -m unittest tests.test_workflow -v
```

### Test Coverage

Current test suite:
- **Core abstractions** (16 tests) - DataSource, Agent, OutputGenerator
- **Registry pattern** (11 tests) - All 6 registries
- **Chainable composition** (18 tests) - Sequential, parallel, DAG
- **L2 layers** (17 tests) - DataLayer, IntelligenceLayer, OutputLayer
- **Workflow class** (15 tests) - Named workflows, checkpointing

**Total: 77 tests - all passing ✅**

---

## Status: What's Implemented

### ✅ Ready Now (Phase 1 Complete)

- Core abstractions (DataSource, Agent, OutputGenerator, etc.)
- Registry pattern for all abstractions
- Chainable composition (|, &, DAG)
- L2 layers (DataLayer, IntelligenceLayer, OutputLayer)
- Named workflows with state management
- Comprehensive test suite (77 tests)
- Production examples

### 🔄 Coming Next (Phase 2)

Real provider implementations:
- **Data**: ChromaDB, Pinecone, PostgreSQL
- **Intelligence**: OpenAI, Anthropic, local models
- **Output**: ReportLab (PDF), python-pptx (PowerPoint)

The abstractions are ready - we're implementing the providers.

---

## Common Patterns

### Sequential Processing

```python
# Process steps in order
workflow = extract | transform | load
result = workflow.invoke(data)
```

### Parallel Processing

```python
# Process steps concurrently
from openbench.core import Parallel

workflow = Parallel([process_a, process_b, process_c])
results = workflow.invoke(data)  # Returns list
```

### Complex DAG

```python
# A → (B & C & D) → E
workflow = (
    step_a
    | Parallel([step_b, step_c, step_d])
    | step_e
)
```

### Conditional Branching

```python
from openbench.core import Conditional

workflow = Conditional(
    condition=lambda x: x["confidence"] > 0.8,
    true_branch=fast_path,
    false_branch=detailed_path
)
```

---

## Troubleshooting

### Import Errors

If you get `ModuleNotFoundError`:

```bash
# Reinstall
pip uninstall openbench
pip install -e .

# Verify
python -c "import openbench; print(openbench.__file__)"
```

### Test Failures

```bash
# Run with verbose output
python -m unittest discover tests -v

# Run single test for debugging
python -m unittest tests.test_workflow.TestWorkflow.test_workflow_creation -v
```

### State Files Accumulating

```bash
# Clean up workflow state (gitignored)
rm -rf workflow_state/
```

---

## Next Steps

1. **Read the API docs**: [docs/API.md](API.md) - Complete API reference
2. **Understand architecture**: [docs/ARCHITECTURE.md](ARCHITECTURE.md) - Vision and design
3. **Explore examples**: Run all three examples to see patterns
4. **Build custom components**: Implement your own DataSource, Agent, or OutputGenerator
5. **Join community**: [Discord](https://discord.com/users/openbench.ai)

---

## Additional Resources

- **GitHub**: [github.com/ai-kitchen-inc/openbench](https://github.com/ai-kitchen-inc/openbench)
- **Issues**: [github.com/ai-kitchen-inc/openbench/issues](https://github.com/ai-kitchen-inc/openbench/issues)
- **Contributing**: [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Email**: openbench2026@gmail.com

---

**Ready to build world-class AI workflows!** 🚀
