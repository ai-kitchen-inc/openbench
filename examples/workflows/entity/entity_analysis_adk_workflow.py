"""
Entity Analysis with ADK - Extract Entities + Analyze with Gemini

Combines LangExtractSource (structured extraction) with GoogleADKAdapter
(Gemini analysis) to demonstrate how Data Layer and Intelligence Layer
work together in OpenBench.

Four demo patterns:
    1. Step-by-step: Extract entities → Analyze with Gemini
    2. Sequential chain: PDFSource → LangExtractSource → ADK analysis
    3. Full pipeline: PDF → Entities → Analysis → Markdown report
    4. Multi-analysis: Same entities, different analysis perspectives

Usage:
    # Run with built-in sample text
    python entity_analysis_adk_workflow.py

    # Run with PDF file
    python entity_analysis_adk_workflow.py report.pdf

    # Run specific demo
    python entity_analysis_adk_workflow.py --demo 1

    # Use OpenAI for extraction, Gemini for analysis
    python entity_analysis_adk_workflow.py --extraction-provider openai

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install langextract google-generativeai
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from openbench.data.sources import LangExtractSource, PDFSource
from openbench.adapters.google_adk import GoogleADKAdapter
from openbench.core.abstractions import RawData


# --- Configuration ---

GEMINI_MODEL = "gemini-2.5-flash"

SAMPLE_TEXT = (
    "Acme Corp announced a strategic partnership with GlobalTech Inc on January 15, 2026. "
    "CEO Sarah Chen stated that the $12M deal will accelerate AI research in healthcare. "
    "Dr. James Rodriguez, Chief Science Officer at GlobalTech, will lead the joint initiative. "
    "The partnership targets a 40% improvement in diagnostic accuracy by Q4 2026. "
    "Acme Corp's board approved the deal unanimously after reviewing Q3 2025 results "
    "showing $850M in revenue, up 23% year-over-year. The NIH has expressed interest "
    "in co-funding the research phase, with an initial commitment of $3.5M. "
    "Operations will be based at Acme's Boston headquarters and GlobalTech's "
    "Singapore R&D center."
)

FEW_SHOT_EXAMPLES = [
    {
        "text": (
            "Dr. Emily Park presented at the Stanford conference on March 10, 2026. "
            "The $1.8M study showed a 28% improvement in patient outcomes."
        ),
        "extractions": [
            {
                "class": "person",
                "text": "Dr. Emily Park",
                "attributes": {"role": "researcher"},
            },
            {
                "class": "organization",
                "text": "Stanford",
                "attributes": {"type": "university"},
            },
            {"class": "date", "text": "March 10, 2026"},
            {
                "class": "amount",
                "text": "$1.8M",
                "attributes": {"purpose": "study funding"},
            },
            {
                "class": "metric",
                "text": "28% improvement",
                "attributes": {"direction": "positive", "domain": "patient outcomes"},
            },
        ],
    },
]

EXTRACTION_PROMPT = """Extract all named entities from the text. For each entity, identify:
- person: People mentioned (with role if clear)
- organization: Companies, institutions, agencies
- date: Dates and time references
- amount: Monetary values, percentages, quantities
- metric: Performance indicators, KPIs, measurements
- location: Places, addresses, regions

Be thorough and extract every entity you find."""


# --- Helpers ---


def check_api_key():
    """Check that GOOGLE_API_KEY is set."""
    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY environment variable is required.")
        print("\nSet it with:")
        print("  export GOOGLE_API_KEY=your-api-key")
        sys.exit(1)


def format_entities_for_llm(result: RawData) -> str:
    """Convert structured entity RawData to readable text for LLM analysis.

    Args:
        result: RawData from LangExtractSource with structured content.

    Returns:
        Formatted text string suitable for LLM prompt.
    """
    content = result.content
    by_class = content["by_class"]
    summary = content["summary"]

    lines = [f"## Extracted Entities ({summary['total']} total)\n"]

    for cls, items in sorted(by_class.items()):
        lines.append(f"### {cls.upper()} ({len(items)} found)")
        for item in items:
            text = item["text"]
            attrs = item.get("attributes", {})
            line = f"- {text}"
            if attrs:
                attr_str = ", ".join(f"{k}={v}" for k, v in attrs.items())
                line += f"  ({attr_str})"
            lines.append(line)
        lines.append("")

    return "\n".join(lines)


def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_analysis(result: Dict[str, Any]):
    """Print ADK analysis result."""
    content = result.get("content", "")
    model = result.get("model", "unknown")
    tokens = result.get("tokens_used")

    print(f"\n  Model: {model}")
    if tokens:
        print(f"  Tokens: {tokens.get('total_tokens', 'N/A')}")
    print(f"\n{content}")


# --- Demo Functions ---


def demo_step_by_step(text: str, provider: str = "gemini"):
    """Demo 1: Step-by-step extraction + analysis.

    Step 1: Extract entities with LangExtractSource
    Step 2: Format entities for LLM
    Step 3: Analyze with GoogleADKAdapter
    """
    print_header("Demo 1: Step-by-Step — Extract + Analyze")

    # Step 1: Entity extraction
    print("\n[Step 1] Extracting entities with LangExtractSource...")
    source = LangExtractSource(
        text=text,
        prompt=EXTRACTION_PROMPT,
        examples=FEW_SHOT_EXAMPLES,
        provider=provider,
    )
    entities = source.extract()

    total = entities.content["summary"]["total"]
    classes = entities.content["summary"]["classes"]
    print(f"  Found {total} entities across {len(classes)} classes")
    for cls, count in sorted(classes.items()):
        print(f"    {cls}: {count}")

    # Step 2: Format for LLM
    print("\n[Step 2] Formatting entities for analysis...")
    formatted = format_entities_for_llm(entities)
    print(f"  Formatted {len(formatted)} characters")

    # Step 3: Analyze with Gemini
    print("\n[Step 3] Analyzing with GoogleADKAdapter (Gemini)...")
    adapter = GoogleADKAdapter(
        model=GEMINI_MODEL,
        system_instruction=(
            "You are an entity analysis expert. Given structured entities extracted "
            "from a document, analyze relationships, patterns, and provide insights. "
            "Be concise and focus on non-obvious connections."
        ),
        generation_config={"temperature": 0.3, "max_output_tokens": 2048},
    )

    result = adapter.invoke({
        "goal": "Analyze the relationships between these entities and identify key insights",
        "data": formatted,
    })

    print_analysis(result)
    return result


def demo_l1_chain(pdf_path: str, provider: str = "gemini"):
    """Demo 2: Sequential chain — PDFSource → LangExtractSource → ADK.

    Extracts text from PDF, feeds into entity extraction,
    then passes structured results to Gemini for analysis.
    """
    print_header("Demo 2: Sequential Chain — PDF → Entities → Analysis")

    print(f"\n  Pipeline: PDFSource({Path(pdf_path).name})")
    print(f"         -> LangExtractSource(provider={provider})")
    print(f"         -> GoogleADKAdapter({GEMINI_MODEL})")

    # Step 1: Extract text from PDF
    print("\n[Step 1] Extracting text from PDF...")
    pdf_source = PDFSource(path=pdf_path)
    pdf_data = pdf_source.extract()
    print(f"  Extracted {len(pdf_data.content)} characters")

    # Step 2: Extract entities from PDF text
    print("\n[Step 2] Extracting entities with LangExtractSource...")
    entity_source = LangExtractSource(
        text=pdf_data.content,
        prompt=EXTRACTION_PROMPT,
        examples=FEW_SHOT_EXAMPLES,
        provider=provider,
    )
    entities = entity_source.extract()

    total = entities.content["summary"]["total"]
    classes = list(entities.content["summary"]["classes"].keys())
    print(f"  Found {total} entities: {', '.join(classes)}")

    # Step 3: Analyze with ADK
    print("\n[Step 3] Analyzing with GoogleADKAdapter...")
    formatted = format_entities_for_llm(entities)
    adapter = GoogleADKAdapter(
        model=GEMINI_MODEL,
        system_instruction="Analyze extracted entities and provide a structured summary.",
        generation_config={"temperature": 0.3, "max_output_tokens": 2048},
    )

    result = adapter.invoke({
        "goal": "Summarize the key entities and their relationships from this document",
        "data": formatted,
    })

    print_analysis(result)
    return result


def demo_l2_composition(pdf_path: str, output_path: str, provider: str = "gemini"):
    """Demo 3: Sequential three-step composition.

    PDF → Entity Extraction → Gemini Analysis → Markdown Report
    """
    print_header("Demo 3: Full Pipeline — PDF → Entities → Analysis → Report")

    print(f"\n  [Step 1] PDFSource → text extraction")
    print(f"  [Step 2] LangExtractSource → entity extraction")
    print(f"  [Step 3] GoogleADKAdapter → entity analysis")
    print(f"  [Step 4] Write Markdown report")

    # Step 1: Extract text from PDF
    print("\n[Step 1] Extracting text from PDF...")
    pdf_data = PDFSource(path=pdf_path).extract()
    print(f"  Extracted {len(pdf_data.content)} characters")

    # Step 2: Extract entities
    print("\n[Step 2] Extracting entities...")
    entity_source = LangExtractSource(
        text=pdf_data.content,
        prompt=EXTRACTION_PROMPT,
        examples=FEW_SHOT_EXAMPLES,
        provider=provider,
    )
    entities = entity_source.extract()

    total = entities.content["summary"]["total"]
    classes = list(entities.content["summary"]["classes"].keys())
    print(f"  Found {total} entities: {', '.join(classes)}")

    # Step 3: Analyze with Gemini
    print("\n[Step 3] Analyzing with GoogleADKAdapter...")
    formatted = format_entities_for_llm(entities)
    adapter = GoogleADKAdapter(
        model=GEMINI_MODEL,
        system_instruction=(
            "You are a document analyst. Analyze the extracted entities and write "
            "a comprehensive report. Format your response in Markdown with sections: "
            "Executive Summary, Key Entities, Relationships, and Recommendations."
        ),
        generation_config={"temperature": 0.3, "max_output_tokens": 4096},
    )

    result = adapter.invoke({
        "goal": "Create a detailed entity analysis report from this document",
        "data": formatted,
    })

    # Step 4: Write Markdown report
    print("\n[Step 4] Writing Markdown report...")
    report_content = result.get("content", "")
    output_file = Path(output_path)
    output_file.write_text(report_content, encoding="utf-8")
    print(f"  Output: {output_file}")
    print(f"  Size: {output_file.stat().st_size} bytes")

    return result


def demo_multi_analysis(text: str, provider: str = "gemini"):
    """Demo 4: Same entities, multiple analysis perspectives.

    Extract once, analyze twice with different goals and temperatures.
    """
    print_header("Demo 4: Multi-Analysis — Different Perspectives")

    # Extract once
    print("\n[Step 1] Extracting entities (single pass)...")
    source = LangExtractSource(
        text=text,
        prompt=EXTRACTION_PROMPT,
        examples=FEW_SHOT_EXAMPLES,
        provider=provider,
    )
    entities = source.extract()
    formatted = format_entities_for_llm(entities)

    total = entities.content["summary"]["total"]
    print(f"  Found {total} entities")

    # Analysis 1: Factual summary (low temperature)
    print("\n[Step 2a] Analysis 1: Factual Summary (temperature=0.1)...")
    summary_adapter = GoogleADKAdapter(
        model=GEMINI_MODEL,
        system_instruction="Provide a factual, data-driven summary. No speculation.",
        generation_config={"temperature": 0.1, "max_output_tokens": 1024},
    )
    summary_result = summary_adapter.invoke({
        "goal": "Create a factual summary of all entities with key statistics",
        "data": formatted,
    })

    print("\n--- Factual Summary ---")
    print(summary_result.get("content", ""))

    # Analysis 2: Strategic insights (higher temperature)
    print("\n[Step 2b] Analysis 2: Strategic Insights (temperature=0.7)...")
    insights_adapter = GoogleADKAdapter(
        model=GEMINI_MODEL,
        system_instruction=(
            "You are a strategic analyst. Identify non-obvious patterns, "
            "potential risks, and opportunities from the entity data."
        ),
        generation_config={"temperature": 0.7, "max_output_tokens": 1024},
    )
    insights_result = insights_adapter.invoke({
        "goal": "Identify strategic patterns, risks, and opportunities",
        "data": formatted,
    })

    print("\n--- Strategic Insights ---")
    print(insights_result.get("content", ""))

    return {"summary": summary_result, "insights": insights_result}


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Entity Analysis with ADK - Extract + Analyze Workflow",
    )
    parser.add_argument(
        "input", nargs="?", default=None,
        help="Path to PDF file (uses built-in sample text if not provided)",
    )
    parser.add_argument(
        "--demo", choices=["1", "2", "3", "4", "all"], default="all",
        help="Which demo to run (default: all)",
    )
    parser.add_argument(
        "--extraction-provider", choices=["gemini", "openai", "ollama"],
        default="gemini", help="Provider for entity extraction (default: gemini)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output path for Demo 3 Markdown report",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Entity Analysis with ADK")
    print("=" * 60)
    print("\n  LangExtractSource (entities) + GoogleADKAdapter (analysis)")
    print(f"  Extraction provider: {args.extraction_provider}")
    print(f"  Analysis model: {GEMINI_MODEL}")

    check_api_key()

    has_pdf = args.input and Path(args.input).exists()

    if args.input and not has_pdf:
        print(f"\nError: File not found: {args.input}")
        sys.exit(1)

    try:
        demos = args.demo

        # Demo 1: Step-by-step (works with text or PDF)
        if demos in ("1", "all"):
            text = SAMPLE_TEXT
            if has_pdf:
                raw = PDFSource(path=args.input).extract()
                text = raw.content
            demo_step_by_step(text, args.extraction_provider)

        # Demo 2: L1 chain (requires PDF)
        if demos in ("2", "all") and has_pdf:
            demo_l1_chain(args.input, args.extraction_provider)
        elif demos == "2" and not has_pdf:
            print("\nDemo 2 requires a PDF file. Provide one as argument.")

        # Demo 3: L2 composition (requires PDF)
        if demos in ("3", "all") and has_pdf:
            output = args.output or "entity_analysis_report.md"
            demo_l2_composition(args.input, output, args.extraction_provider)
        elif demos == "3" and not has_pdf:
            print("\nDemo 3 requires a PDF file. Provide one as argument.")

        # Demo 4: Multi-analysis (works with text or PDF)
        if demos in ("4", "all"):
            text = SAMPLE_TEXT
            if has_pdf:
                raw = PDFSource(path=args.input).extract()
                text = raw.content
            demo_multi_analysis(text, args.extraction_provider)

        print(f"\n{'=' * 60}")
        print("Done!")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
