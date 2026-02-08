"""
OpenBench PDF → Google ADK → PDF Workflow

Demonstrates a complete end-to-end workflow:
1. Data Layer: Extract text from PDF using PDFSource
2. Intelligence Layer: Process with Google Gemini via GoogleADKAdapter
3. Output Layer: Generate new PDF with PDFGenerator

Key Concepts:
- Three-layer architecture: Data → Intelligence → Output
- L2 orchestration: Compose layers using | operator
- Framework adapters: GoogleADKAdapter wraps Google Generative AI

Requirements:
- pip install openbench[google,output]
- Set GOOGLE_API_KEY environment variable
- Input PDF file

Usage:
    python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.pdf
    python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.pdf --goal "Summarize in bullet points"
    python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.md --format markdown
"""

import argparse
import os
import sys
from datetime import datetime

from openbench.adapters.google_adk import GoogleADKAdapter

# OpenBench imports
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer
from openbench.data.sources.pdf import PDFSource
from openbench.output.generators import MarkdownGenerator, PDFGenerator
from openbench.workflows import Workflow

# =============================================================================
# Configuration - Change these values as needed
# =============================================================================
MODEL_NAME = "gemini-3-flash-preview"  # Google Gemini model to use
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096


def check_requirements(input_pdf: str) -> None:
    """Check that all requirements are met."""
    # Check API key
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY environment variable is required.")
        print("\nSet it with:")
        print("  export GOOGLE_API_KEY=your-api-key")
        sys.exit(1)

    # Check input file exists
    if not os.path.exists(input_pdf):
        print(f"Error: Input PDF not found: {input_pdf}")
        sys.exit(1)


def run_pdf_workflow(input_pdf: str, output_pdf: str, goal: str) -> dict:
    """
    Run PDF → Google ADK → PDF workflow.

    Args:
        input_pdf: Path to input PDF file
        output_pdf: Path to output PDF file
        goal: Task/goal for the AI to perform

    Returns:
        Workflow result dict
    """
    print("\n" + "=" * 80)
    print("PDF → Google ADK → PDF Workflow")
    print("=" * 80)

    # Create components
    pdf_source = PDFSource(path=input_pdf)
    google_adapter = GoogleADKAdapter(
        model=MODEL_NAME,
        system_instruction="You are a document analysis assistant. Be concise and informative.",
        generation_config={
            "temperature": DEFAULT_TEMPERATURE,
            "max_output_tokens": DEFAULT_MAX_TOKENS,
        },
    )
    pdf_generator = PDFGenerator(template="report")

    # Compose workflow using L2 layers
    workflow = (
        DataLayer(sources=pdf_source)
        | IntelligenceLayer(agents=google_adapter)
        | OutputLayer(generators=pdf_generator)
    )

    print(f"\nInput:  {input_pdf}")
    print(f"Output: {output_pdf}")
    print(f"Goal:   {goal}")
    print(f"Model:  {MODEL_NAME}")
    print("\nExecuting workflow...")

    # Execute
    result = workflow.invoke(
        {
            "goal": goal,
            "output_path": output_pdf,
            "title": f"Document Analysis - {datetime.now().strftime('%Y-%m-%d')}",
        }
    )

    print("\n✓ Workflow completed!")

    if result.get("generated_outputs"):
        output = result["generated_outputs"][0]
        print(f"  Output file: {output.file_path}")
        print(f"  Size: {output.size_bytes} bytes")

    return result


def run_markdown_workflow(input_pdf: str, output_md: str, goal: str) -> dict:
    """
    Run PDF → Google ADK → Markdown workflow.

    Args:
        input_pdf: Path to input PDF file
        output_md: Path to output Markdown file
        goal: Task/goal for the AI to perform

    Returns:
        Workflow result dict
    """
    print("\n" + "=" * 80)
    print("PDF → Google ADK → Markdown Workflow")
    print("=" * 80)

    # Create components
    pdf_source = PDFSource(path=input_pdf)
    google_adapter = GoogleADKAdapter(
        model=MODEL_NAME,
        system_instruction="You are a document analysis assistant. Format your response in Markdown.",
        generation_config={
            "temperature": DEFAULT_TEMPERATURE,
            "max_output_tokens": DEFAULT_MAX_TOKENS,
        },
    )
    md_generator = MarkdownGenerator(add_toc=True)

    # Compose workflow
    workflow = (
        DataLayer(sources=pdf_source)
        | IntelligenceLayer(agents=google_adapter)
        | OutputLayer(generators=md_generator)
    )

    print(f"\nInput:  {input_pdf}")
    print(f"Output: {output_md}")
    print(f"Goal:   {goal}")
    print(f"Model:  {MODEL_NAME}")
    print("\nExecuting workflow...")

    result = workflow.invoke({"goal": goal, "output_path": output_md, "title": "Document Analysis"})

    print("\n✓ Workflow completed!")

    if result.get("generated_outputs"):
        output = result["generated_outputs"][0]
        print(f"  Output file: {output.file_path}")
        print(f"  Size: {output.size_bytes} bytes")

    return result


def run_named_workflow(input_pdf: str, output_pdf: str, goal: str) -> dict:
    """
    Run named workflow with state management and checkpointing.

    Args:
        input_pdf: Path to input PDF file
        output_pdf: Path to output PDF file
        goal: Task/goal for the AI to perform

    Returns:
        Workflow result dict
    """
    print("\n" + "=" * 80)
    print("Named Workflow with State Management")
    print("=" * 80)

    # Create components
    pdf_source = PDFSource(path=input_pdf)
    google_adapter = GoogleADKAdapter(model=MODEL_NAME)
    pdf_generator = PDFGenerator(template="report")

    # Create named workflow with checkpoints
    workflow = Workflow(
        name="pdf-analysis",
        chain=(
            DataLayer(sources=pdf_source)
            | IntelligenceLayer(agents=google_adapter)
            | OutputLayer(generators=pdf_generator)
        ),
        checkpoints=True,
    )

    print(f"\nWorkflow: {workflow.name}")
    print("Checkpoints: Enabled")
    print(f"Goal: {goal}")
    print("\nExecuting workflow...")

    # Execute
    result = workflow.run({"goal": goal, "output_path": output_pdf})

    print("\n✓ Named workflow completed!")
    print(f"  State ID: {workflow.state_id}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="PDF → Google ADK → PDF Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python pdf_google_adk_workflow.py input.pdf output.pdf
    python pdf_google_adk_workflow.py input.pdf output.pdf --goal "Summarize key points"
    python pdf_google_adk_workflow.py input.pdf output.md --format markdown
    python pdf_google_adk_workflow.py input.pdf output.pdf --workflow named

Environment:
    GOOGLE_API_KEY    Required (get from https://aistudio.google.com/apikey)
        """,
    )
    parser.add_argument("input_pdf", nargs="?", help="Input PDF file path")
    parser.add_argument("output", nargs="?", help="Output file path (.pdf or .md)")
    parser.add_argument(
        "--goal",
        "-g",
        default="Summarize this document and extract key insights",
        help="Goal/task for the AI to perform",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["pdf", "markdown"],
        default="pdf",
        help="Output format (default: pdf)",
    )
    parser.add_argument(
        "--workflow",
        "-w",
        choices=["basic", "named"],
        default="basic",
        help="Workflow type (default: basic)",
    )

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print(" " * 15 + "OpenBench: PDF → Google ADK → PDF Workflow")
    print("=" * 80)
    print("\nThree-Layer Architecture:")
    print("  [Data Layer] → [Intelligence Layer] → [Output Layer]")
    print("  PDFSource   →   GoogleADKAdapter   →   PDFGenerator")

    # Validate required arguments for workflow execution
    if not args.input_pdf or not args.output:
        print("\nError: input_pdf and output are required.")
        parser.print_help()
        sys.exit(1)

    # Check requirements
    check_requirements(args.input_pdf)

    # Determine output format
    is_markdown = args.format == "markdown" or args.output.endswith(".md")

    # Run appropriate workflow
    if args.workflow == "named":
        run_named_workflow(args.input_pdf, args.output, args.goal)
    elif is_markdown:
        run_markdown_workflow(args.input_pdf, args.output, args.goal)
    else:
        run_pdf_workflow(args.input_pdf, args.output, args.goal)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("""
✓ PDFSource extracts text from PDFs
✓ GoogleADKAdapter processes with Google Gemini
✓ PDFGenerator/MarkdownGenerator creates output
✓ Layers compose with | operator
✓ Same pattern works for any data source → any AI → any output
""")
    print("=" * 80)


if __name__ == "__main__":
    main()
