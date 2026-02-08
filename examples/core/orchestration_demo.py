"""
L1/L2 Orchestration Demo

Demonstrates two-level orchestration:
- L1: Component-level composition (sources, agents, generators)
- L2: System-level composition (layers)

Example Scenario:
- 3 YouTube video sources
- 1 Dictionary source
- 1 Table data source
- Research and analysis agents
- PDF and PPTX output generators
"""

from datetime import datetime
from typing import Any

from openbench.core import (
    Agent,
    # Registries
    Chain,
    DataLayer,
    # Abstractions (L1 components)
    DataSource,
    DataStore,
    ExecutionContext,
    ExecutionResult,
    GeneratedOutput,
    IntelligenceLayer,
    OutputGenerator,
    OutputLayer,
    Parallel,
    Query,
    RawData,
    SearchResult,
    create_workflow,
)

# ============================================================================
# L1 Component Implementations
# ============================================================================


class YouTubeSource(DataSource):
    """Mock YouTube video source."""

    def __init__(self, url: str):
        self.url = url
        self._id = url.split("/")[-1]

    @property
    def source_type(self) -> str:
        return "youtube"

    @property
    def source_id(self) -> str:
        return f"youtube:{self._id}"

    def get_metadata(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": f"Video {self._id}",
            "duration": "10:30",
            "views": 1000000,
        }

    def extract(self) -> RawData:
        print(f"  📹 Extracting video: {self.url}")
        return RawData(
            content=f"Transcript from video {self._id}...",
            content_type="text",
            metadata=self.get_metadata(),
            source=self,
        )

    def validate(self) -> bool:
        return True


class DictionarySource(DataSource):
    """Mock dictionary/glossary source."""

    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "dictionary"

    @property
    def source_id(self) -> str:
        return f"dict:{self.path}"

    def get_metadata(self) -> dict[str, Any]:
        return {"path": self.path, "entries": 150}

    def extract(self) -> RawData:
        print(f"  📚 Loading dictionary: {self.path}")
        return RawData(
            content={"term1": "definition1", "term2": "definition2"},
            content_type="structured",
            metadata=self.get_metadata(),
            source=self,
        )

    def validate(self) -> bool:
        return True


class TableSource(DataSource):
    """Mock table/CSV data source."""

    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "table"

    @property
    def source_id(self) -> str:
        return f"table:{self.path}"

    def get_metadata(self) -> dict[str, Any]:
        return {"path": self.path, "rows": 500, "columns": 10}

    def extract(self) -> RawData:
        print(f"  📊 Loading table: {self.path}")
        return RawData(
            content=[["col1", "col2"], ["val1", "val2"]],
            content_type="structured",
            metadata=self.get_metadata(),
            source=self,
        )

    def validate(self) -> bool:
        return True


class MockVectorStore(DataStore):
    """Mock vector store."""

    def __init__(self, collection: str):
        self.collection = collection
        self._data = []

    @property
    def store_type(self) -> str:
        return "vector"

    def index(self, data: RawData, **options) -> str:
        item_id = f"item_{len(self._data)}"
        self._data.append({"id": item_id, "data": data})
        print(f"    💾 Indexed in {self.collection}: {item_id}")
        return item_id

    def search(self, query: Query) -> SearchResult:
        return SearchResult(items=self._data[: query.limit], total=len(self._data))

    def get(self, item_id: str) -> Any | None:
        return next((item for item in self._data if item["id"] == item_id), None)

    def delete(self, item_id: str) -> bool:
        self._data = [item for item in self._data if item["id"] != item_id]
        return True

    def update(self, item_id: str, data: Any) -> bool:
        for item in self._data:
            if item["id"] == item_id:
                item["data"] = data
                return True
        return False


class ResearchAgent(Agent):
    """Mock research agent."""

    def __init__(self, goal: str):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "research"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"  🔍 Research: {context.goal}")
        return ExecutionResult(
            output={"findings": f"Research completed for: {context.goal}"},
            status="completed",
            metadata={"agent": "research"},
            cost=0.01,
            tokens_used=100,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.01


class AnalysisAgent(Agent):
    """Mock analysis agent."""

    def __init__(self, goal: str):
        self.goal = goal

    @property
    def agent_type(self) -> str:
        return "analysis"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"  📊 Analysis: {context.goal}")
        return ExecutionResult(
            output={"insights": f"Analysis completed for: {context.goal}"},
            status="completed",
            metadata={"agent": "analysis"},
            cost=0.02,
            tokens_used=200,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.02


class PDFGenerator(OutputGenerator):
    """Mock PDF generator."""

    def __init__(self, template: str = "default"):
        self.template = template

    @property
    def output_format(self) -> str:
        return "pdf"

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        template = template or self.template
        file_path = f"outputs/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        print(f"  📄 Generating PDF: {file_path}")
        return GeneratedOutput(
            file_path=file_path, format="pdf", size_bytes=5120, metadata={"template": template}
        )

    def validate(self, content: Any) -> bool:
        return True


class PPTXGenerator(OutputGenerator):
    """Mock PPTX generator."""

    def __init__(self, template: str = "default"):
        self.template = template

    @property
    def output_format(self) -> str:
        return "pptx"

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        template = template or self.template
        file_path = f"outputs/presentation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
        print(f"  📊 Generating PPTX: {file_path}")
        return GeneratedOutput(
            file_path=file_path, format="pptx", size_bytes=10240, metadata={"template": template}
        )

    def validate(self, content: Any) -> bool:
        return True


# ============================================================================
# Demo 1: L1 Component-Level Composition
# ============================================================================


def demo_l1_composition():
    """Demonstrate L1 component-level composition."""
    print("\n" + "=" * 70)
    print("DEMO 1: L1 Component-Level Composition")
    print("=" * 70)

    print("\n1️⃣  Sequential Data Sources (video1 | video2 | video3)")
    print("-" * 70)

    # Chain 3 video sources sequentially
    video_pipeline = Chain(
        [
            YouTubeSource(url="https://youtube.com/watch?v=video1"),
            YouTubeSource(url="https://youtube.com/watch?v=video2"),
            YouTubeSource(url="https://youtube.com/watch?v=video3"),
        ]
    )

    result = video_pipeline.invoke({})
    print(f"\n  ✅ Processed {len(result) if isinstance(result, list) else 1} videos\n")

    print("2️⃣  Parallel Data Sources (dict & table)")
    print("-" * 70)

    # Run dictionary and table in parallel
    reference_data = Parallel(
        [
            DictionarySource(path="./data/glossary.json"),
            TableSource(path="./data/metrics.csv"),
        ]
    )

    result = reference_data.invoke({})
    print(f"\n  ✅ Processed {len(result)} reference sources\n")

    print("3️⃣  Sequential Agents (research | analysis)")
    print("-" * 70)

    # Chain agents
    agent_pipeline = Chain(
        [
            ResearchAgent(goal="Extract themes"),
            AnalysisAgent(goal="Identify trends"),
        ]
    )

    result = agent_pipeline.invoke({"data": "sample data"})
    print("\n  ✅ Agent pipeline completed\n")

    print("4️⃣  Parallel Outputs (pdf & pptx)")
    print("-" * 70)

    # Generate multiple outputs in parallel
    output_pipeline = Parallel(
        [
            PDFGenerator(template="corporate"),
            PPTXGenerator(template="executive"),
        ]
    )

    result = output_pipeline.invoke({"content": "analysis results"})
    print(f"\n  ✅ Generated {len(result)} outputs\n")


# ============================================================================
# Demo 2: L2 System-Level Composition
# ============================================================================


def demo_l2_composition():
    """Demonstrate L2 system-level layer composition."""
    print("\n" + "=" * 70)
    print("DEMO 2: L2 System-Level Composition (Layers)")
    print("=" * 70)

    print("\n🔧 Building L2 Workflow...")
    print("-" * 70)

    # L1: Compose data sources (3 videos sequential, then dict & table parallel)
    print("\nL1 Data Sources:")
    print("  - 3 YouTube videos (sequential)")
    print("  - Dictionary & Table (parallel)")

    video_sources = Chain(
        [
            YouTubeSource(url="https://youtube.com/watch?v=sustainability1"),
            YouTubeSource(url="https://youtube.com/watch?v=sustainability2"),
            YouTubeSource(url="https://youtube.com/watch?v=sustainability3"),
        ]
    )

    reference_sources = Parallel(
        [
            DictionarySource(path="./data/sustainability_glossary.json"),
            TableSource(path="./data/emission_data.csv"),
        ]
    )

    # Combine: videos first, then references
    all_sources = video_sources | reference_sources

    # L1: Compose agents
    print("\nL1 Agents:")
    print("  - Research → Analysis → Synthesis")

    agents = Chain(
        [
            ResearchAgent(goal="Extract sustainability themes"),
            AnalysisAgent(goal="Analyze emission trends"),
            ResearchAgent(goal="Synthesize recommendations"),
        ]
    )

    # L1: Compose outputs
    print("\nL1 Outputs:")
    print("  - PDF & PPTX (parallel)")

    outputs = Parallel(
        [
            PDFGenerator(template="sustainability_report"),
            PPTXGenerator(template="executive_presentation"),
        ]
    )

    # L2: Create layers
    print("\nL2 Layers:")
    print("  - DataLayer | IntelligenceLayer | OutputLayer")

    data_layer = DataLayer(
        sources=all_sources, stores=[MockVectorStore(collection="sustainability")]
    )

    intelligence_layer = IntelligenceLayer(agents=agents)
    output_layer = OutputLayer(generators=outputs)

    # L2: Compose complete workflow
    complete_workflow = data_layer | intelligence_layer | output_layer

    print("\n" + "=" * 70)
    print("🚀 EXECUTING E2E WORKFLOW")
    print("=" * 70)

    # Execute!
    result = complete_workflow.invoke(
        {"project": "Q1 2026 Sustainability Report", "company": "Acme Corp"}
    )

    print("\n" + "=" * 70)
    print("✅ WORKFLOW COMPLETED")
    print("=" * 70)

    # Print results
    data_metadata = result.get("metadata", {})
    result.get("intelligence_output", {})
    outputs_data = result.get("generated_outputs", [])

    print("\n📊 Results:")
    print(f"  - Data sources processed: {data_metadata.get('num_sources', 0)}")
    print(f"  - Items indexed: {data_metadata.get('num_indexed', 0)}")
    print("  - Intelligence tasks completed: ✓")
    print(f"  - Outputs generated: {len(outputs_data)}")

    if outputs_data:
        print("\n📁 Generated Files:")
        for output in outputs_data:
            print(f"  - {output.file_path}")


# ============================================================================
# Demo 3: Using create_workflow Helper
# ============================================================================


def demo_create_workflow_helper():
    """Demonstrate create_workflow helper function."""
    print("\n" + "=" * 70)
    print("DEMO 3: create_workflow() Helper Function")
    print("=" * 70)

    print("\n💡 The create_workflow() helper simplifies L2 workflow creation")
    print("-" * 70)

    # Create L1 components
    data_sources = Chain(
        [
            YouTubeSource(url="https://youtube.com/watch?v=v1"),
            YouTubeSource(url="https://youtube.com/watch?v=v2"),
        ]
    )

    agents = Chain(
        [
            ResearchAgent(goal="Research"),
            AnalysisAgent(goal="Analyze"),
        ]
    )

    outputs = PDFGenerator(template="simple")

    # Create complete workflow in one call
    workflow = create_workflow(
        data_sources=data_sources,
        data_stores=[MockVectorStore(collection="demo")],
        agents=agents,
        generators=outputs,
    )

    print("\n🚀 Executing workflow created with create_workflow()...")
    print("-" * 70)

    result = workflow.invoke({"project": "Demo Project"})

    print("\n✅ Workflow completed!")
    print(f"   Generated: {result.get('generated_outputs', [None])[0].file_path}")


# ============================================================================
# Demo 4: Complex DAG at L1 Level
# ============================================================================


def demo_complex_l1_dag():
    """Demonstrate complex L1 DAG within DataLayer."""
    print("\n" + "=" * 70)
    print("DEMO 4: Complex L1 DAG within DataLayer")
    print("=" * 70)

    print("\n📐 Complex Data Source DAG:")
    print("-" * 70)
    print("  Branch A: video1 | video2 | video3 (sequential)")
    print("  Branch B: dict (single)")
    print("  Branch C: table (single)")
    print("  Pattern: A & B & C (all parallel at top level)")

    # Complex DAG: 3 parallel branches
    branch_a = Chain(
        [
            YouTubeSource(url="https://youtube.com/watch?v=a1"),
            YouTubeSource(url="https://youtube.com/watch?v=a2"),
            YouTubeSource(url="https://youtube.com/watch?v=a3"),
        ]
    )

    branch_b = DictionarySource(path="./data/terms.json")

    branch_c = TableSource(path="./data/stats.csv")

    # All branches run in parallel
    complex_dag = Parallel([branch_a, branch_b, branch_c])

    # Use in DataLayer
    data_layer = DataLayer(sources=complex_dag, stores=[MockVectorStore(collection="complex")])

    print("\n🚀 Executing complex DAG...")
    print("-" * 70)

    result = data_layer.invoke({})

    print("\n✅ Complex DAG completed!")
    print(f"   Total sources processed: {result['metadata']['num_sources']}")
    print(f"   Items indexed: {result['metadata']['num_indexed']}")


# ============================================================================
# Main Demo Runner
# ============================================================================


def main():
    """Run all L1/L2 orchestration demos."""
    print("\n" + "🚀" * 35)
    print("OpenBench L1/L2 Orchestration Demo")
    print("🚀" * 35)

    print("\nThis demo shows:")
    print("  • L1: Component-level composition (sources, agents, outputs)")
    print("  • L2: System-level composition (layers)")
    print("  • E2E: Complete workflows with both levels")

    # Run demos
    demo_l1_composition()
    demo_l2_composition()
    demo_create_workflow_helper()
    demo_complex_l1_dag()

    print("\n" + "=" * 70)
    print("✅ ALL DEMOS COMPLETED")
    print("=" * 70)

    print("\n📚 Key Takeaways:")
    print("  1. ✅ L1 composition: Pipe (|) and parallel (&) operators")
    print("  2. ✅ L2 composition: DataLayer | IntelligenceLayer | OutputLayer")
    print("  3. ✅ All abstractions (DataSource, Agent, OutputGenerator) are Chainable")
    print("  4. ✅ Layers (DataLayer, IntelligenceLayer, OutputLayer) are Chainable")
    print("  5. ✅ Build complex DAGs at both L1 and L2 levels")
    print("  6. ✅ E2E orchestration: from data ingestion to output generation")

    print("\n💡 Example from this demo:")
    print("  L1: (video1 | video2 | video3) & dict & table")
    print("  L2: DataLayer | IntelligenceLayer | OutputLayer")
    print("  Result: Complete E2E workflow\n")


if __name__ == "__main__":
    main()
