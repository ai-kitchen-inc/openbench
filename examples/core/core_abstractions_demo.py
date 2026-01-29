"""
Demonstration of OpenBench Core Abstractions.

Shows how to:
1. Create custom implementations of abstract interfaces
2. Register implementations with registries
3. Build DAG workflows using Chainable
4. Use state management for checkpointing
"""

from typing import Any, Dict, Optional
from openbench.core import (
    # Abstractions
    DataSource, RawData, Query, SearchResult, DataStore,
    Agent, ExecutionContext, ExecutionResult,
    OutputGenerator, GeneratedOutput,
    # Registries
    DataSourceRegistry, DataStoreRegistry, AgentRegistry, OutputGeneratorRegistry,
    # Chainable
    Chainable, Chain, Parallel, Conditional, Router, Lambda, RunnableConfig,
    # State
    WorkflowState, StateStore, LocalStateStore, StatefulChainable,
)
from datetime import datetime


# ============================================================================
# Step 1: Create Custom Implementations
# ============================================================================

@DataSourceRegistry.register('pdf', 'mock', description='Mock PDF data source for testing')
class MockPDFSource(DataSource):
    """Mock PDF data source implementation."""

    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "pdf"

    @property
    def source_id(self) -> str:
        return f"pdf:{self.path}"

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "size": 1024,
            "pages": 10,
        }

    def extract(self) -> RawData:
        return RawData(
            content=f"Mock content from {self.path}",
            content_type="text",
            metadata=self.get_metadata(),
            source=self
        )

    def validate(self) -> bool:
        return True


@DataStoreRegistry.register('vector', 'mock', description='Mock vector database for testing')
class MockVectorStore(DataStore):
    """Mock vector database implementation."""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self._data = []

    @property
    def store_type(self) -> str:
        return "vector"

    def index(self, data: RawData, **options) -> str:
        item_id = f"item_{len(self._data)}"
        self._data.append({
            "id": item_id,
            "content": data.content,
            "metadata": data.metadata
        })
        return item_id

    def search(self, query: Query) -> SearchResult:
        # Mock search - return first N items
        items = self._data[:query.limit]
        return SearchResult(
            items=items,
            total=len(self._data),
            scores=[0.95] * len(items)
        )

    def get(self, item_id: str) -> Optional[Any]:
        for item in self._data:
            if item["id"] == item_id:
                return item
        return None

    def delete(self, item_id: str) -> bool:
        self._data = [item for item in self._data if item["id"] != item_id]
        return True

    def update(self, item_id: str, data: Any) -> bool:
        for item in self._data:
            if item["id"] == item_id:
                item.update(data)
                return True
        return False


@AgentRegistry.register('research', 'mock', description='Mock research agent for testing')
class MockResearchAgent(Agent):
    """Mock research agent implementation."""

    def __init__(self, goal: str):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "research"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"🔍 Research Agent executing: {context.goal}")
        return ExecutionResult(
            output={"research": f"Research findings for: {context.goal}"},
            status="completed",
            metadata={"agent_type": "research"},
            cost=0.01,
            tokens_used=100
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.01


@AgentRegistry.register('analysis', 'mock', description='Mock analysis agent for testing')
class MockAnalysisAgent(Agent):
    """Mock analysis agent implementation."""

    def __init__(self, goal: str):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "analysis"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"📊 Analysis Agent executing: {context.goal}")
        return ExecutionResult(
            output={"analysis": f"Analysis results for: {context.goal}"},
            status="completed",
            metadata={"agent_type": "analysis"},
            cost=0.02,
            tokens_used=200
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.02


@OutputGeneratorRegistry.register('pdf', 'mock', description='Mock PDF generator for testing')
class MockPDFGenerator(OutputGenerator):
    """Mock PDF generator implementation."""

    def __init__(self, style: str = "default"):
        self.style = style

    @property
    def output_format(self) -> str:
        return "pdf"

    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        **options
    ) -> GeneratedOutput:
        file_path = f"outputs/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        print(f"📄 Generating PDF: {file_path}")
        return GeneratedOutput(
            file_path=file_path,
            format="pdf",
            size_bytes=5120,
            metadata={"template": template, "style": self.style}
        )

    def validate(self, content: Any) -> bool:
        return True


# ============================================================================
# Note: All implementations are auto-registered via @Registry.register decorator
# No manual registration needed!
# ============================================================================


# ============================================================================
# Step 3: Create Chainable Workflow Components
# ============================================================================

class DataLoaderChain(Chainable):
    """Chainable that loads data from a source."""

    def __init__(self, source_type: str, provider: str, **config):
        self.source = DataSourceRegistry.create(source_type, provider, **config)

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Any:
        print(f"📥 Loading data from {self.source.source_type}...")
        raw_data = self.source.extract()
        return {
            "raw_data": raw_data,
            "metadata": raw_data.metadata
        }


class AgentChain(Chainable):
    """Chainable that wraps an agent."""

    def __init__(self, agent_type: str, provider: str, goal: str):
        self.agent = AgentRegistry.create(agent_type, provider, goal=goal)

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Any:
        context = ExecutionContext(
            goal=self.agent.goal,
            data=input
        )
        result = self.agent.execute(context)
        return {
            **input,  # Pass through previous data
            f"{self.agent.agent_type}_result": result.output
        }


class OutputChain(Chainable):
    """Chainable that generates output."""

    def __init__(self, format: str, provider: str, **config):
        self.generator = OutputGeneratorRegistry.create(format, provider, **config)

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Any:
        print(f"📤 Generating {self.generator.output_format} output...")
        output = self.generator.generate(
            content=input,
            template="default"
        )
        return {
            **input,
            "output_file": output.file_path
        }


# ============================================================================
# Step 4: Build DAG Workflows
# ============================================================================

def demo_sequential_workflow():
    """Demonstrate sequential workflow: A → B → C"""
    print("\n" + "="*60)
    print("DEMO 1: Sequential Workflow (A → B → C)")
    print("="*60)

    # Create workflow using pipe operator
    workflow = (
        DataLoaderChain('pdf', 'mock', path='./docs/sample.pdf')
        | AgentChain('research', 'mock', goal='Analyze document')
        | AgentChain('analysis', 'mock', goal='Summarize findings')
        | OutputChain('pdf', 'mock', style='corporate')
    )

    # Execute
    result = workflow.invoke({})
    print(f"\n✅ Workflow completed!")
    print(f"Output file: {result.get('output_file')}")


def demo_parallel_workflow():
    """Demonstrate parallel workflow: [A, B, C]"""
    print("\n" + "="*60)
    print("DEMO 2: Parallel Workflow [A & B & C]")
    print("="*60)

    # Load data
    loader = DataLoaderChain('pdf', 'mock', path='./docs/sample.pdf')

    # Create parallel agents
    parallel_analysis = (
        AgentChain('research', 'mock', goal='Research trends')
        & AgentChain('analysis', 'mock', goal='Analyze data')
        & AgentChain('research', 'mock', goal='Find insights')
    )

    # Combine: Load → Parallel Analysis
    workflow = loader | parallel_analysis

    # Execute
    result = workflow.invoke({})
    print(f"\n✅ Parallel workflow completed!")
    print(f"Results: {len(result)} branches executed")


def demo_conditional_workflow():
    """Demonstrate conditional workflow."""
    print("\n" + "="*60)
    print("DEMO 3: Conditional Workflow (if/else)")
    print("="*60)

    # Conditional routing based on input
    workflow = Conditional(
        condition=lambda x: x.get('task_type') == 'research',
        true_branch=AgentChain('research', 'mock', goal='Do research'),
        false_branch=AgentChain('analysis', 'mock', goal='Do analysis')
    )

    # Test both branches
    print("\nTest 1: task_type='research'")
    result1 = workflow.invoke({'task_type': 'research'})
    print(f"Result: {list(result1.keys())}")

    print("\nTest 2: task_type='analysis'")
    result2 = workflow.invoke({'task_type': 'analysis'})
    print(f"Result: {list(result2.keys())}")


def demo_router_workflow():
    """Demonstrate router workflow (multi-way branching)."""
    print("\n" + "="*60)
    print("DEMO 4: Router Workflow (multi-way)")
    print("="*60)

    # Multi-way router
    workflow = Router(
        routes={
            'research': AgentChain('research', 'mock', goal='Research task'),
            'analysis': AgentChain('analysis', 'mock', goal='Analysis task'),
        },
        router=lambda x: x['task_type'],
        default=AgentChain('research', 'mock', goal='Default task')
    )

    # Test different routes
    for task_type in ['research', 'analysis', 'other']:
        print(f"\nRouting task_type='{task_type}'")
        result = workflow.invoke({'task_type': task_type})
        print(f"Result: {list(result.keys())}")


def demo_complex_dag():
    """Demonstrate complex DAG with multiple patterns."""
    print("\n" + "="*60)
    print("DEMO 5: Complex DAG")
    print("="*60)

    # Complex workflow:
    # Load → [Research & Analysis] → Generate Output

    loader = DataLoaderChain('pdf', 'mock', path='./docs/sample.pdf')

    parallel_agents = (
        AgentChain('research', 'mock', goal='Research')
        & AgentChain('analysis', 'mock', goal='Analyze')
    )

    # Merge results from parallel execution
    merge = Lambda(lambda x: {
        "merged_results": x,
        "summary": "Combined analysis and research"
    })

    generator = OutputChain('pdf', 'mock')

    # Build workflow
    workflow = loader | parallel_agents | merge | generator

    # Execute
    result = workflow.invoke({})
    print(f"\n✅ Complex DAG completed!")


# ============================================================================
# Step 5: State Management & Checkpointing
# ============================================================================

def demo_stateful_workflow():
    """Demonstrate workflow with state management."""
    print("\n" + "="*60)
    print("DEMO 6: Stateful Workflow (Checkpointing)")
    print("="*60)

    # Create simple workflow
    workflow = (
        AgentChain('research', 'mock', goal='Step 1')
        | AgentChain('analysis', 'mock', goal='Step 2')
    )

    # Wrap with state management
    state_store = LocalStateStore(base_path="./workflow_state")
    stateful_workflow = StatefulChainable(
        chainable=workflow,
        state_store=state_store,
        workflow_name="demo_workflow"
    )

    # Execute with auto-checkpointing
    print("\n🚀 Executing stateful workflow...")
    result = stateful_workflow.invoke({})

    # List workflows
    print("\n📋 Listing workflows:")
    workflows = state_store.list_workflows()
    for wf in workflows:
        print(f"  - {wf.workflow_id}: {wf.status.value} ({len(wf.steps)} steps)")


# ============================================================================
# Step 6: Configuration-Driven Creation
# ============================================================================

def demo_config_driven():
    """Demonstrate configuration-driven workflow creation."""
    print("\n" + "="*60)
    print("DEMO 7: Configuration-Driven Creation")
    print("="*60)

    # User configuration (could come from YAML)
    config = {
        "data_source": {
            "type": "pdf",
            "provider": "mock",
            "path": "./docs/sample.pdf"
        },
        "agent": {
            "type": "research",
            "provider": "mock",
            "goal": "Analyze document"
        },
        "output": {
            "format": "pdf",
            "provider": "mock",
            "style": "modern"
        }
    }

    # Create components from config
    source = DataSourceRegistry.create(
        config['data_source']['type'],
        config['data_source']['provider'],
        path=config['data_source']['path']
    )

    agent = AgentRegistry.create(
        config['agent']['type'],
        config['agent']['provider'],
        goal=config['agent']['goal']
    )

    generator = OutputGeneratorRegistry.create(
        config['output']['format'],
        config['output']['provider'],
        style=config['output']['style']
    )

    print(f"✅ Created from config:")
    print(f"  - DataSource: {source.source_type}")
    print(f"  - Agent: {agent.agent_type}")
    print(f"  - Output: {generator.output_format}")

    print("\n💡 To switch providers, just change config:")
    print("   provider: 'mock' → 'pinecone' (code stays the same!)")


# ============================================================================
# Main Demo
# ============================================================================

def main():
    """Run all demonstrations."""
    print("\n" + "🚀"*30)
    print("OpenBench Core Abstractions Demo")
    print("🚀"*30)

    # Note: All implementations are auto-registered via decorators!
    print("✅ All implementations registered via @Registry.register decorators!")

    # Run demos
    demo_sequential_workflow()
    demo_parallel_workflow()
    demo_conditional_workflow()
    demo_router_workflow()
    demo_complex_dag()
    demo_stateful_workflow()
    demo_config_driven()

    print("\n" + "="*60)
    print("✅ All demos completed!")
    print("="*60)

    print("\n📚 Key Takeaways:")
    print("  1. ✅ Registry pattern enables provider selection")
    print("  2. ✅ Chainable interface supports DAG workflows")
    print("  3. ✅ Pipe operator (|) makes composition easy")
    print("  4. ✅ State management enables checkpointing")
    print("  5. ✅ Configuration-driven = no vendor lock-in")
    print("\n")


if __name__ == "__main__":
    main()
