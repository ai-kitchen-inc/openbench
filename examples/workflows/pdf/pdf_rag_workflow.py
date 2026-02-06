"""
PDF RAG Workflow - Using OpenBench Workflow Pattern

Demonstrates the proper OpenBench workflow pattern:
    PDFSource -> PineconeStore -> GoogleADK -> MarkdownGenerator

Uses:
    - Workflow class for named, stateful execution
    - DataLayer, IntelligenceLayer, OutputLayer (L2 composition)
    - Pipe operator (|) for sequential chaining

Requires:
    - PINECONE_API_KEY environment variable
    - GOOGLE_API_KEY environment variable

Usage:
    python examples/workflows/pdf/pdf_rag_workflow.py <pdf-path>
    python examples/workflows/pdf/pdf_rag_workflow.py document.pdf -o report.md
    python examples/workflows/pdf/pdf_rag_workflow.py document.pdf -q "What is this about?"
"""

import argparse
import os
import sys
from pathlib import Path

from openbench.workflows import Workflow
from openbench.core.layers import DataLayer, IntelligenceLayer, OutputLayer
from openbench.data.sources import PDFSource
from openbench.data.stores import PineconeStore
from openbench.intelligence import GoogleEmbeddingProvider
from openbench.adapters import GoogleADKAdapter
from openbench.output.generators import MarkdownGenerator


def check_api_keys():
    """Check if required API keys are set."""
    missing = []
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")

    if missing:
        print("Error: Missing environment variables:")
        for key in missing:
            print(f"  - {key}")
        print("\nSet them with:")
        print("  export PINECONE_API_KEY=your-key")
        print("  export GOOGLE_API_KEY=your-key")
        sys.exit(1)


def create_workflow(
    pdf_path: str,
    output_path: str,
    goal: str,
    index_name: str = "openbench",
    namespace: str = "pdf-rag",
) -> Workflow:
    """
    Create PDF RAG workflow using OpenBench pattern.

    Pipeline: PDFSource -> PineconeStore -> GoogleADK -> MarkdownGenerator
    """
    # Components
    pdf_source = PDFSource(path=pdf_path)

    embedding_provider = GoogleEmbeddingProvider(model="text-embedding-004")

    vector_store = PineconeStore(
        index_name=index_name,
        namespace=namespace,
        embedding_provider=embedding_provider,
        create_if_missing=True,
    )

    llm = GoogleADKAdapter(
        model="gemini-2.5-flash",
        system_instruction=f"""You are a document analyst.
        Task: {goal}
        Analyze the document content and provide a comprehensive response.
        Format your response in Markdown.""",
    )

    output_generator = MarkdownGenerator(output_path=output_path)

    # Compose workflow using L2 layers and pipe operator
    workflow = Workflow(
        name="pdf-rag-workflow",
        chain=(
            DataLayer(sources=pdf_source, stores=[vector_store])
            | IntelligenceLayer(agents=llm)
            | OutputLayer(generators=output_generator)
        ),
        checkpoints=True,
    )

    return workflow


def main():
    parser = argparse.ArgumentParser(
        description="PDF RAG Workflow using OpenBench pattern"
    )
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("-o", "--output", default="output/rag_report.md")
    parser.add_argument("-q", "--question", default="Analyze and summarize this document")
    parser.add_argument("--index", default="openbench", help="Pinecone index name")
    parser.add_argument("--namespace", default="pdf-rag", help="Pinecone namespace")
    args = parser.parse_args()

    print("=" * 60)
    print("OpenBench PDF RAG Workflow")
    print("=" * 60)
    print("\nPattern: Workflow(chain=DataLayer | IntelligenceLayer | OutputLayer)")
    print(f"\nPipeline:")
    print(f"  PDFSource({Path(args.pdf).name})")
    print(f"  -> PineconeStore({args.index}/{args.namespace})")
    print(f"  -> GoogleADK(gemini-2.5-flash)")
    print(f"  -> MarkdownGenerator({args.output})")

    check_api_keys()

    if not Path(args.pdf).exists():
        print(f"\nError: PDF not found: {args.pdf}")
        sys.exit(1)

    try:
        # Create workflow
        print("\n[1/2] Creating workflow...")
        workflow = create_workflow(
            pdf_path=args.pdf,
            output_path=args.output,
            goal=args.question,
            index_name=args.index,
            namespace=args.namespace,
        )
        print(f"  Workflow: {workflow.name}")

        # Run workflow
        print("\n[2/2] Running workflow...")
        result = workflow.run({
            "goal": args.question,
            "output_path": args.output,
            "title": f"Analysis: {Path(args.pdf).stem}",
        })

        print("\n" + "=" * 60)
        print("Done!")
        print("=" * 60)

        # Show results
        if result.get("generated_outputs"):
            output = result["generated_outputs"][0]
            print(f"\nOutput: {output.file_path}")
            print(f"Size: {output.size_bytes} bytes")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
