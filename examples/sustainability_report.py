"""
World-Class Example: Sustainability Report Generation

Demonstrates the power of OpenBench's L1/L2 orchestration with Workflow.

This example shows:
- L1 component composition (data sources, agents, outputs)
- L2 layer composition (DataLayer | IntelligenceLayer | OutputLayer)
- Named Workflow with automatic checkpointing
- Complex DAG: parallel data ingestion, sequential analysis, parallel outputs
"""

from typing import Any, Dict, Optional
from openbench.core import (
    # L1 Abstractions (Chainable components)
    DataSource, RawData, Agent, ExecutionContext, ExecutionResult,
    OutputGenerator, GeneratedOutput,
    # L1 Composition
    Chain, Parallel,
    # L2 Layers
    DataLayer, IntelligenceLayer, OutputLayer,
    # Registries
    DataSourceRegistry, AgentRegistry, OutputGeneratorRegistry,
    # Store
    DataStore, Query, SearchResult,
)
from openbench.workflows import Workflow
from datetime import datetime


# ============================================================================
# Component Implementations
# ============================================================================

class PDFSource(DataSource):
    """Extract data from PDF documents."""

    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "pdf"

    @property
    def source_id(self) -> str:
        return f"pdf:{self.path}"

    def get_metadata(self) -> Dict[str, Any]:
        return {"path": self.path, "type": "pdf"}

    def extract(self) -> RawData:
        print(f"  📄 Extracting: {self.path}")
        return RawData(
            content=f"Sustainability data from {self.path}",
            content_type="text",
            metadata=self.get_metadata(),
            source=self
        )

    def validate(self) -> bool:
        return True


class APISource(DataSource):
    """Fetch data from REST API."""

    def __init__(self, url: str):
        self.url = url

    @property
    def source_type(self) -> str:
        return "api"

    @property
    def source_id(self) -> str:
        return f"api:{self.url}"

    def get_metadata(self) -> Dict[str, Any]:
        return {"url": self.url, "type": "api"}

    def extract(self) -> RawData:
        print(f"  🌐 Fetching: {self.url}")
        return RawData(
            content={"esg_score": 78, "carbon_emissions": 1250},
            content_type="structured",
            metadata=self.get_metadata(),
            source=self
        )

    def validate(self) -> bool:
        return True


class CSVSource(DataSource):
    """Load data from CSV file."""

    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "csv"

    @property
    def source_id(self) -> str:
        return f"csv:{self.path}"

    def get_metadata(self) -> Dict[str, Any]:
        return {"path": self.path, "rows": 500}

    def extract(self) -> RawData:
        print(f"  📊 Loading: {self.path}")
        return RawData(
            content=[["Month", "Emissions"], ["Jan", "1200"], ["Feb", "1100"]],
            content_type="structured",
            metadata=self.get_metadata(),
            source=self
        )

    def validate(self) -> bool:
        return True


class MockVectorStore(DataStore):
    """Simple in-memory vector store."""

    def __init__(self, collection: str):
        self.collection = collection
        self._data = []

    @property
    def store_type(self) -> str:
        return "vector"

    def index(self, data: RawData, **options) -> str:
        item_id = f"{self.collection}_{len(self._data)}"
        self._data.append({"id": item_id, "data": data})
        print(f"    💾 Indexed: {item_id}")
        return item_id

    def search(self, query: Query) -> SearchResult:
        return SearchResult(items=self._data[:query.limit], total=len(self._data))

    def get(self, item_id: str) -> Optional[Any]:
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
    """Research agent for gathering insights."""

    def __init__(self, goal: str, depth: str = "comprehensive"):
        self.goal = goal
        self.depth = depth

    @property
    def agent_type(self) -> str:
        return "research"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"  🔍 Research: {context.goal}")
        print(f"     Depth: {self.depth}")
        return ExecutionResult(
            output={
                "findings": f"Research findings for {context.goal}",
                "sources": ["sustainability_report.pdf", "esg_data.json"],
                "confidence": 0.92
            },
            status="completed",
            metadata={"depth": self.depth},
            cost=0.05,
            tokens_used=500
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.05


class AnalysisAgent(Agent):
    """Analysis agent for trend analysis."""

    def __init__(self, goal: str, methods: list = None):
        self.goal = goal
        self.methods = methods or ["trend_analysis"]

    @property
    def agent_type(self) -> str:
        return "analysis"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"  📊 Analysis: {context.goal}")
        print(f"     Methods: {', '.join(self.methods)}")
        return ExecutionResult(
            output={
                "trends": "Carbon emissions decreased 15% YoY",
                "recommendations": ["Increase renewable energy", "Improve efficiency"],
                "confidence": 0.88
            },
            status="completed",
            metadata={"methods": self.methods},
            cost=0.08,
            tokens_used=800
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.08


class ContentAgent(Agent):
    """Content generation agent."""

    def __init__(self, goal: str, style: str = "executive", length: str = "8_pages"):
        self.goal = goal
        self.style = style
        self.length = length

    @property
    def agent_type(self) -> str:
        return "content"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"  ✍️  Content: {context.goal}")
        print(f"     Style: {self.style}, Length: {self.length}")
        return ExecutionResult(
            output={
                "content": f"Executive sustainability report ({self.length})",
                "sections": ["Executive Summary", "ESG Metrics", "Recommendations"],
                "word_count": 4500
            },
            status="completed",
            metadata={"style": self.style, "length": self.length},
            cost=0.12,
            tokens_used=1200
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.12


class PDFGenerator(OutputGenerator):
    """Generate PDF reports."""

    def __init__(self, template: str = "default"):
        self.template = template

    @property
    def output_format(self) -> str:
        return "pdf"

    def generate(self, content: Any, template: Optional[str] = None, **options) -> GeneratedOutput:
        template = template or self.template
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = f"outputs/sustainability_report_{timestamp}.pdf"
        print(f"  📄 PDF: {file_path}")
        return GeneratedOutput(
            file_path=file_path,
            format="pdf",
            size_bytes=2048000,
            metadata={"template": template}
        )

    def validate(self, content: Any) -> bool:
        return True


class PPTXGenerator(OutputGenerator):
    """Generate PowerPoint presentations."""

    def __init__(self, template: str = "default"):
        self.template = template

    @property
    def output_format(self) -> str:
        return "pptx"

    def generate(self, content: Any, template: Optional[str] = None, **options) -> GeneratedOutput:
        template = template or self.template
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = f"outputs/sustainability_presentation_{timestamp}.pptx"
        print(f"  📊 PPTX: {file_path}")
        return GeneratedOutput(
            file_path=file_path,
            format="pptx",
            size_bytes=5120000,
            metadata={"template": template}
        )

    def validate(self, content: Any) -> bool:
        return True


# ============================================================================
# Main Example: World-Class Workflow
# ============================================================================

def main():
    """Generate sustainability report using world-class abstractions."""

    print("\n" + "="*70)
    print("OpenBench: Sustainability Report Generation")
    print("World-Class L1/L2 Orchestration + Workflow")
    print("="*70)

    # ========================================================================
    # L1: Component-Level Composition
    # ========================================================================

    print("\n🔧 Building L1 Component Workflows...")
    print("-" * 70)

    # Data sources: Parallel ingestion from multiple sources
    data_sources = Parallel([
        PDFSource("./data/sustainability_report_2025.pdf"),
        APISource("https://api.company.com/esg-metrics"),
        CSVSource("./data/carbon_emissions.csv"),
    ])
    print("  ✓ Data sources: PDF & API & CSV (parallel)")

    # Agents: Sequential analysis pipeline
    agents = Chain([
        ResearchAgent(
            goal="Gather sustainability data and ESG metrics",
            depth="comprehensive"
        ),
        AnalysisAgent(
            goal="Analyze carbon emissions trends and identify improvements",
            methods=["trend_analysis", "statistical"]
        ),
        ContentAgent(
            goal="Draft comprehensive sustainability report",
            style="executive",
            length="8_pages"
        ),
    ])
    print("  ✓ Agents: Research → Analysis → Content (sequential)")

    # Outputs: Parallel generation of multiple formats
    outputs = Parallel([
        PDFGenerator(template="corporate"),
        PPTXGenerator(template="executive"),
    ])
    print("  ✓ Outputs: PDF & PPTX (parallel)")

    # ========================================================================
    # L2: System-Level Composition
    # ========================================================================

    print("\n🏗️  Building L2 Layer Workflow...")
    print("-" * 70)

    # Create layers with L1 workflows inside
    data_layer = DataLayer(
        sources=data_sources,
        stores=[MockVectorStore(collection="sustainability")]
    )
    print("  ✓ DataLayer created")

    intelligence_layer = IntelligenceLayer(agents=agents)
    print("  ✓ IntelligenceLayer created")

    output_layer = OutputLayer(generators=outputs)
    print("  ✓ OutputLayer created")

    # Compose layers into complete pipeline
    pipeline = data_layer | intelligence_layer | output_layer
    print("  ✓ Pipeline: DataLayer | IntelligenceLayer | OutputLayer")

    # ========================================================================
    # Workflow: Named, Stateful Execution
    # ========================================================================

    print("\n🚀 Creating Named Workflow with Checkpointing...")
    print("-" * 70)

    workflow = Workflow(
        name="sustainability-report-generator",
        chain=pipeline,
        checkpoints=True,
        metadata={
            "project": "Q1 2026 Sustainability Report",
            "company": "Acme Corp",
            "version": "1.0"
        }
    )
    print(f"  ✓ Workflow created: {workflow.name}")
    print(f"  ✓ Checkpoints: enabled")

    # ========================================================================
    # Execute End-to-End
    # ========================================================================

    print("\n" + "="*70)
    print("▶️  EXECUTING WORKFLOW")
    print("="*70)

    result = workflow.run({
        "project": "Q1 2026 Sustainability Report",
        "company": "Acme Corp"
    })

    # ========================================================================
    # Results
    # ========================================================================

    print("\n" + "="*70)
    print("✅ WORKFLOW COMPLETED")
    print("="*70)

    outputs_generated = result.get('generated_outputs', [])
    print(f"\n📊 Results:")
    print(f"  - Data sources processed: 3")
    print(f"  - Analysis stages: 3 (Research → Analysis → Content)")
    print(f"  - Outputs generated: {len(outputs_generated)}")

    if outputs_generated:
        print(f"\n📁 Generated Files:")
        for output in outputs_generated:
            size_mb = output.size_bytes / (1024 * 1024)
            print(f"  - {output.file_path} ({size_mb:.1f} MB)")

    print("\n💡 Key Features Demonstrated:")
    print("  ✓ L1 composition: Parallel data sources, sequential agents, parallel outputs")
    print("  ✓ L2 composition: DataLayer | IntelligenceLayer | OutputLayer")
    print("  ✓ Named workflow with automatic checkpointing")
    print("  ✓ Clean, expressive API - no 'parallel=True/False' needed!")
    print("  ✓ DAG structure visible in code")

    print("\n🎯 This is world-class abstraction.")
    print("")


if __name__ == "__main__":
    main()
