"""
Entity Extraction Workflow - Structured Extraction from Documents

Demonstrates OpenBench LangExtractSource for structured entity extraction:
    Pipeline: PDFSource -> LangExtractSource -> Structured Entities

Features:
    - PDF text extraction with LangExtract entity extraction
    - Few-shot examples for domain-specific extraction
    - Class filtering (extract only specific entity types)
    - Multi-provider support (Gemini, OpenAI, Ollama)
    - Source grounding (positions mapped to original text)

Usage:
    # Extract from PDF
    python entity_extraction_workflow.py report.pdf

    # Extract from text file
    python entity_extraction_workflow.py document.txt --format text

    # With specific entity classes only
    python entity_extraction_workflow.py report.pdf --classes person date amount

    # Using OpenAI provider
    python entity_extraction_workflow.py report.pdf --provider openai

    # Multiple extraction passes for long documents
    python entity_extraction_workflow.py report.pdf --passes 3

Requires:
    - GOOGLE_API_KEY environment variable (for Gemini provider)
    - OPENAI_API_KEY environment variable (for OpenAI provider)
    - pip install langextract
"""

import argparse
import os
import sys
from pathlib import Path

from openbench.core.abstractions import RawData
from openbench.data.sources import LangExtractSource, PDFSource

# --- Few-shot Examples ---

GENERAL_EXAMPLES = [
    {
        "text": (
            "Dr. Sarah Chen presented findings at the MIT conference on March 15, 2026. "
            "The study, funded by a $2.5M NIH grant, showed a 34% improvement in outcomes."
        ),
        "extractions": [
            {
                "class": "person",
                "text": "Dr. Sarah Chen",
                "attributes": {"role": "researcher"},
            },
            {
                "class": "organization",
                "text": "MIT",
                "attributes": {"type": "university"},
            },
            {
                "class": "date",
                "text": "March 15, 2026",
            },
            {
                "class": "amount",
                "text": "$2.5M",
                "attributes": {"purpose": "grant funding", "source": "NIH"},
            },
            {
                "class": "metric",
                "text": "34% improvement",
                "attributes": {"direction": "positive"},
            },
        ],
    },
    {
        "text": "Acme Corp acquired GlobalTech Inc for $500M on January 10, 2026.",
        "extractions": [
            {
                "class": "organization",
                "text": "Acme Corp",
                "attributes": {"role": "acquirer"},
            },
            {
                "class": "organization",
                "text": "GlobalTech Inc",
                "attributes": {"role": "acquired"},
            },
            {
                "class": "amount",
                "text": "$500M",
                "attributes": {"type": "acquisition"},
            },
            {
                "class": "date",
                "text": "January 10, 2026",
            },
        ],
    },
]

DEFAULT_PROMPT = """Extract all named entities from the text. For each entity, identify:
- person: People mentioned (with role if clear)
- organization: Companies, institutions, agencies
- date: Dates and time references
- amount: Monetary values, percentages, quantities
- metric: Performance indicators, KPIs, measurements
- location: Places, addresses, regions

Be thorough and extract every entity you find."""


# --- Helper Functions ---


def check_api_keys(provider: str):
    """Check if required API keys are set for the provider."""
    required = {
        "gemini": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }

    if provider in required:
        key_name = required[provider]
        if not os.getenv(key_name):
            print(f"Error: Missing environment variable: {key_name}")
            print("\nSet it with:")
            print(f"  export {key_name}=your-api-key")
            sys.exit(1)


def load_text_file(path: str) -> str:
    """Load text content from a file."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def extract_from_pdf(pdf_path: str) -> str:
    """Extract raw text from PDF using PDFSource."""
    print("\n[1/3] Extracting text from PDF...")
    source = PDFSource(path=pdf_path)

    if not source.validate():
        print(f"  ✗ Invalid PDF: {pdf_path}")
        sys.exit(1)

    raw_data = source.extract()
    text = raw_data.content
    pages = raw_data.metadata.get("total_pages", "?")
    print(f"  ✓ Extracted {len(text):,} characters from {pages} pages")
    return text


def run_extraction(
    text: str,
    provider: str,
    prompt: str,
    examples: list[dict],
    filter_classes: list[str] | None = None,
    extraction_passes: int = 1,
    max_workers: int = 10,
) -> RawData:
    """Run LangExtract entity extraction on text."""
    print("\n[2/3] Running entity extraction...")
    print(f"  Provider: {provider}")
    print(f"  Passes: {extraction_passes}")
    if filter_classes:
        print(f"  Filter: {', '.join(filter_classes)}")

    source = LangExtractSource(
        prompt=prompt,
        text=text,
        examples=examples,
        provider=provider,
        extraction_passes=extraction_passes,
        max_workers=max_workers,
        filter_classes=filter_classes,
    )

    result = source.extract()

    total = result.content["summary"]["total"]
    classes = result.content["summary"]["classes"]
    print(f"  ✓ Found {total} entities across {len(classes)} classes")

    return result


def display_results(result: RawData):
    """Display extraction results in formatted output."""
    print("\n[3/3] Results")
    print("-" * 60)

    by_class = result.content["by_class"]
    summary = result.content["summary"]

    for cls, items in sorted(by_class.items()):
        print(f"\n  [{cls.upper()}] ({len(items)} found)")
        for item in items:
            text = item["text"]
            attrs = item.get("attributes", {})
            pos = item.get("position", {})

            line = f"    - {text}"
            if attrs:
                attr_str = ", ".join(f"{k}={v}" for k, v in attrs.items())
                line += f"  ({attr_str})"
            if pos.get("start") is not None:
                line += f"  [pos: {pos['start']}-{pos['end']}]"
            print(line)

    print(f"\n{'=' * 60}")
    print(f"Total: {summary['total']} entities")
    for cls, count in sorted(summary["classes"].items()):
        print(f"  {cls}: {count}")
    print(f"{'=' * 60}")


def run_workflow_composition(pdf_path: str, provider: str):
    """Demonstrate workflow composition: PDFSource | LangExtractSource."""
    print("\n" + "=" * 60)
    print("Workflow Composition Demo")
    print("=" * 60)

    print("\nPipeline:")
    print(f"  PDFSource({Path(pdf_path).name})")
    print(f"  -> LangExtractSource(provider={provider})")
    print("  -> Structured Entities")

    # Compose using pipe operator
    workflow = PDFSource(path=pdf_path) | LangExtractSource(
        prompt=DEFAULT_PROMPT,
        examples=GENERAL_EXAMPLES,
        provider=provider,
    )

    print(f"\n  Workflow type: {type(workflow).__name__}")
    print("  Running workflow...")

    result = workflow.invoke({})

    total = result.content["summary"]["total"]
    classes = list(result.content["summary"]["classes"].keys())
    print(f"  ✓ Extracted {total} entities: {', '.join(classes)}")

    return result


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Entity Extraction Workflow - Extract structured entities from documents"
    )
    parser.add_argument("input", help="Path to PDF or text file")
    parser.add_argument(
        "--format",
        choices=["pdf", "text"],
        default="pdf",
        help="Input format (default: pdf)",
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "openai", "ollama"],
        default="gemini",
        help="LLM provider (default: gemini)",
    )
    parser.add_argument(
        "--classes",
        nargs="+",
        default=None,
        help="Extract only these entity classes (e.g., person date amount)",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=1,
        help="Extraction passes for better recall (default: 1)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Parallel workers for long documents (default: 10)",
    )
    parser.add_argument(
        "--compose",
        action="store_true",
        help="Use workflow composition (pipe operator) instead of step-by-step",
    )
    args = parser.parse_args()

    # Validate input
    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    print("=" * 60)
    print("OpenBench Entity Extraction Workflow")
    print("=" * 60)
    print(f"\n  Input: {Path(args.input).name}")
    print(f"  Format: {args.format}")
    print(f"  Provider: {args.provider}")

    check_api_keys(args.provider)

    try:
        if args.compose and args.format == "pdf":
            # Workflow composition mode
            result = run_workflow_composition(args.input, args.provider)
            display_results(result)
        else:
            # Step-by-step mode
            if args.format == "pdf":
                text = extract_from_pdf(args.input)
            else:
                text = load_text_file(args.input)
                print(f"\n[1/3] Loaded text file: {len(text):,} characters")

            result = run_extraction(
                text=text,
                provider=args.provider,
                prompt=DEFAULT_PROMPT,
                examples=GENERAL_EXAMPLES,
                filter_classes=args.classes,
                extraction_passes=args.passes,
                max_workers=args.workers,
            )

            display_results(result)

        print("\nDone!")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
