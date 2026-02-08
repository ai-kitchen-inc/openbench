"""
Sustainability Report Generation Example

Demonstrates OpenBench's L1/L2 orchestration with real implementations:
- Real PDFSource for PDF extraction
- ProjectContext for multi-tenant isolation
- L1 component composition (data sources, agents, outputs)
- L2 layer composition (DataLayer | IntelligenceLayer | OutputLayer)
- Named Workflow with automatic checkpointing
"""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from openbench.core import (
    Agent,
    # L1 Composition
    Chain,
    # L2 Layers
    DataLayer,
    # L1 Abstractions
    DataSource,
    # Data Store
    DataStore,
    ExecutionContext,
    ExecutionResult,
    GeneratedOutput,
    IntelligenceLayer,
    OutputGenerator,
    OutputLayer,
    Parallel,
    # Project Context
    ProjectContext,
    Query,
    RawData,
    SearchResult,
)

# Import real PDFSource
from openbench.data import PDFSource
from openbench.workflows import Workflow

# ============================================================================
# Helper: Create Sample PDF for Demo
# ============================================================================


def create_sample_pdf(path: Path) -> bool:
    """Create a sample PDF file for demonstration."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(str(path), pagesize=letter)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(100, 750, "Sustainability Report 2025")
        c.setFont("Helvetica", 12)
        c.drawString(100, 720, "Executive Summary")
        c.drawString(100, 700, "This report outlines our environmental initiatives.")
        c.drawString(100, 680, "Key Metrics:")
        c.drawString(120, 660, "- Carbon emissions reduced by 15%")
        c.drawString(120, 640, "- Renewable energy usage increased to 45%")
        c.drawString(120, 620, "- Water consumption reduced by 10%")
        c.drawString(100, 580, "ESG Score: 78/100")
        c.save()
        return True
    except ImportError:
        return False


# ============================================================================
# Mock Components (for sources not yet implemented)
# ============================================================================


class APISource(DataSource):
    """Fetch data from REST API (mock implementation)."""

    def __init__(self, url: str, project: ProjectContext | None = None):
        self.url = url
        self.project = project

    @property
    def source_type(self) -> str:
        return "api"

    @property
    def source_id(self) -> str:
        return f"api:{self.url}"

    def get_metadata(self) -> dict[str, Any]:
        metadata = {"url": self.url, "type": "api"}
        if self.project:
            metadata["project_id"] = self.project.project_id
        return metadata

    def extract(self) -> RawData:
        print(f"  🌐 Fetching: {self.url}")
        return RawData(
            content={"esg_score": 78, "carbon_emissions": 1250, "renewable_pct": 45},
            content_type="structured",
            metadata=self.get_metadata(),
            source=self,
        )

    def validate(self) -> bool:
        return True


class CSVSource(DataSource):
    """Load data from CSV file (mock implementation)."""

    def __init__(self, path: str, project: ProjectContext | None = None):
        self.path = path
        self.project = project

    @property
    def source_type(self) -> str:
        return "csv"

    @property
    def source_id(self) -> str:
        return f"csv:{self.path}"

    def get_metadata(self) -> dict[str, Any]:
        metadata = {"path": self.path, "rows": 500}
        if self.project:
            metadata["project_id"] = self.project.project_id
        return metadata

    def extract(self) -> RawData:
        print(f"  📊 Loading: {self.path}")
        return RawData(
            content=[
                ["Month", "Emissions", "Target"],
                ["Jan", "1200", "1300"],
                ["Feb", "1100", "1250"],
                ["Mar", "1050", "1200"],
            ],
            content_type="structured",
            metadata=self.get_metadata(),
            source=self,
        )

    def validate(self) -> bool:
        return True


class MockVectorStore(DataStore):
    """In-memory vector store (mock implementation)."""

    def __init__(self, collection: str, project: ProjectContext | None = None):
        self.collection = collection
        self.project = project
        self._data: list[dict] = []
        # Use project namespace if available
        self.namespace = project.namespace if project else "default"

    @property
    def store_type(self) -> str:
        return "vector"

    def index(self, data: RawData, **options) -> str:
        item_id = f"{self.namespace}_{self.collection}_{len(self._data)}"
        self._data.append({"id": item_id, "data": data})
        print(f"    💾 Indexed: {item_id}")
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
                "confidence": 0.92,
            },
            status="completed",
            metadata={"depth": self.depth},
            cost=0.05,
            tokens_used=500,
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.05


class AnalysisAgent(Agent):
    """Analysis agent for trend analysis."""

    def __init__(self, goal: str, methods: list | None = None):
        self.goal = goal
        self.methods = methods or ["trend_analysis"]

    @property
    def agent_type(self) -> str:
        return "analysis"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        print(f"  📈 Analysis: {context.goal}")
        print(f"     Methods: {', '.join(self.methods)}")
        return ExecutionResult(
            output={
                "trends": "Carbon emissions decreased 15% YoY",
                "recommendations": ["Increase renewable energy", "Improve efficiency"],
                "confidence": 0.88,
            },
            status="completed",
            metadata={"methods": self.methods},
            cost=0.08,
            tokens_used=800,
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
                "word_count": 4500,
            },
            status="completed",
            metadata={"style": self.style, "length": self.length},
            cost=0.12,
            tokens_used=1200,
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

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        template = template or self.template
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = f"outputs/sustainability_report_{timestamp}.pdf"
        print(f"  📄 Generated: {file_path}")
        return GeneratedOutput(
            file_path=file_path, format="pdf", size_bytes=2048000, metadata={"template": template}
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

    def generate(self, content: Any, template: str | None = None, **options) -> GeneratedOutput:
        template = template or self.template
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = f"outputs/sustainability_presentation_{timestamp}.pptx"
        print(f"  📊 Generated: {file_path}")
        return GeneratedOutput(
            file_path=file_path, format="pptx", size_bytes=5120000, metadata={"template": template}
        )

    def validate(self, content: Any) -> bool:
        return True


# ============================================================================
# Main Example
# ============================================================================


def main():
    """Generate sustainability report with real PDFSource and ProjectContext."""

    print("\n" + "=" * 70)
    print("OpenBench: Sustainability Report Generation")
    print("Real PDFSource + ProjectContext + L1/L2 Orchestration")
    print("=" * 70)

    # ========================================================================
    # Create Project Context
    # ========================================================================

    print("\n📁 Creating Project Context...")
    print("-" * 70)

    project = ProjectContext(
        name="Q1 2026 Sustainability Report",
        description="Annual sustainability metrics and ESG analysis",
        user_id="analyst@acme.com",
        organization_id="acme-corp",
    )

    print(f"  ✓ Project ID: {project.project_id}")
    print(f"  ✓ Name: {project.name}")
    print(f"  ✓ Namespace: {project.namespace}")

    # ========================================================================
    # Setup Data Sources with Real PDFSource
    # ========================================================================

    print("\n🔧 Building L1 Component Workflows...")
    print("-" * 70)

    # Create temporary directory for sample files
    temp_dir = Path(tempfile.mkdtemp())
    sample_pdf = temp_dir / "sustainability_report_2025.pdf"

    # Try to create sample PDF
    pdf_source = None
    if create_sample_pdf(sample_pdf):
        print(f"  ✓ Created sample PDF: {sample_pdf.name}")
        # Use REAL PDFSource from openbench.data
        pdf_source = PDFSource(path=sample_pdf, project=project)
        print("  ✓ Using real PDFSource (openbench.data.PDFSource)")
    else:
        print("  ⚠ reportlab not installed, skipping real PDF demo")
        print("    Install with: pip install reportlab")

    # Build data sources (parallel ingestion)
    sources_list = []
    if pdf_source:
        sources_list.append(pdf_source)
    sources_list.extend(
        [
            APISource("https://api.company.com/esg-metrics", project=project),
            CSVSource("./data/carbon_emissions.csv", project=project),
        ]
    )

    data_sources = Parallel(sources_list)
    print(f"  ✓ Data sources: {len(sources_list)} sources (parallel)")

    # Agents: Sequential analysis pipeline
    agents = Chain(
        [
            ResearchAgent(goal="Gather sustainability data and ESG metrics", depth="comprehensive"),
            AnalysisAgent(
                goal="Analyze carbon emissions trends",
                methods=["trend_analysis", "statistical", "yoy_comparison"],
            ),
            ContentAgent(
                goal="Draft comprehensive sustainability report",
                style="executive",
                length="8_pages",
            ),
        ]
    )
    print("  ✓ Agents: Research → Analysis → Content (sequential)")

    # Outputs: Parallel generation
    outputs = Parallel(
        [
            PDFGenerator(template="corporate"),
            PPTXGenerator(template="executive"),
        ]
    )
    print("  ✓ Outputs: PDF & PPTX (parallel)")

    # ========================================================================
    # L2: System-Level Composition
    # ========================================================================

    print("\n🏗️  Building L2 Layer Workflow...")
    print("-" * 70)

    # Vector store with project namespace for isolation
    vector_store = MockVectorStore(collection="sustainability", project=project)
    print(f"  ✓ VectorStore namespace: {vector_store.namespace}")

    data_layer = DataLayer(sources=data_sources, stores=[vector_store])
    print("  ✓ DataLayer created")

    intelligence_layer = IntelligenceLayer(agents=agents)
    print("  ✓ IntelligenceLayer created")

    output_layer = OutputLayer(generators=outputs)
    print("  ✓ OutputLayer created")

    # Compose layers
    pipeline = data_layer | intelligence_layer | output_layer
    print("  ✓ Pipeline: DataLayer | IntelligenceLayer | OutputLayer")

    # ========================================================================
    # Workflow: Named, Stateful Execution
    # ========================================================================

    print("\n🚀 Creating Named Workflow...")
    print("-" * 70)

    workflow = Workflow(
        name="sustainability-report-generator",
        chain=pipeline,
        checkpoints=True,
        metadata={
            "project_id": project.project_id,
            "project_name": project.name,
            "company": "Acme Corp",
            "version": "2.0",
        },
    )
    print(f"  ✓ Workflow: {workflow.name}")
    print(f"  ✓ Project: {project.project_id}")
    print("  ✓ Checkpoints: enabled")

    # ========================================================================
    # Execute
    # ========================================================================

    print("\n" + "=" * 70)
    print("▶️  EXECUTING WORKFLOW")
    print("=" * 70)

    result = workflow.run(
        {"project_id": project.project_id, "project_name": project.name, "company": "Acme Corp"}
    )

    # ========================================================================
    # Results
    # ========================================================================

    print("\n" + "=" * 70)
    print("✅ WORKFLOW COMPLETED")
    print("=" * 70)

    # Show PDF extraction result if available
    if pdf_source:
        print("\n📄 PDF Extraction Result:")
        try:
            raw_data = pdf_source.extract()
            content_preview = (
                raw_data.content[:200] + "..." if len(raw_data.content) > 200 else raw_data.content
            )
            print(f"  Content preview: {content_preview}")
            print(f"  Pages: {raw_data.metadata.get('total_pages', 'N/A')}")
            print(
                f"  Project ID: {raw_data.metadata.get('project_context', {}).get('project_id', 'N/A')}"
            )
        except Exception as e:
            print(f"  Error: {e}")

    outputs_generated = result.get("generated_outputs", [])
    print("\n📊 Summary:")
    print(f"  - Project: {project.name}")
    print(f"  - Project ID: {project.project_id}")
    print(f"  - Data sources: {len(sources_list)}")
    print("  - Analysis stages: 3 (Research → Analysis → Content)")
    print(f"  - Outputs generated: {len(outputs_generated)}")

    if outputs_generated:
        print("\n📁 Generated Files:")
        for output in outputs_generated:
            size_mb = output.size_bytes / (1024 * 1024)
            print(f"  - {output.file_path} ({size_mb:.1f} MB)")

    print("\n💡 Key Features Demonstrated:")
    print("  ✓ Real PDFSource from openbench.data")
    print("  ✓ ProjectContext for multi-tenant isolation")
    print("  ✓ Vector store namespace = project_id")
    print("  ✓ L1 composition: Parallel sources, sequential agents")
    print("  ✓ L2 composition: DataLayer | IntelligenceLayer | OutputLayer")
    print("  ✓ Named workflow with checkpointing")

    # Cleanup
    if sample_pdf.exists():
        sample_pdf.unlink()
    temp_dir.rmdir()

    print("\n")


if __name__ == "__main__":
    main()
