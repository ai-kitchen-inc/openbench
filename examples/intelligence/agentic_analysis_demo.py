"""
Agentic Analysis Demo - AnalysisAgent + StructuredOutputAgent

Three agentic approaches to data analysis:

    1. AnalysisAgent + Tools: Analysis with calculate + web search tools
    2. Document Analysis: AnalysisAgent + RAG (auto-retrieve from knowledge base)
    3. Structured Output: StructuredOutputAgent returns validated JSON

Usage:
    python agentic_analysis_demo.py                     # all demos
    python agentic_analysis_demo.py --demo 1            # tools only
    python agentic_analysis_demo.py --demo 3            # structured output
    python agentic_analysis_demo.py --demo 1 --query "analyze AI market growth"
    python agentic_analysis_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY (required)
    - PINECONE_API_KEY (optional -- Demo 2 skips if not set)
    - pip install google-genai pinecone
"""

import argparse
import json
import math
import os
import sys
from typing import Any

from openbench.core.abstractions import ExecutionContext
from openbench.core.providers import ProviderType, configure_provider
from openbench.data.sources import GroundedSearchSource
from openbench.intelligence.agents import AnalysisAgent
from openbench.intelligence.base import StructuredOutputAgent
from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

# --- Constants ---

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_NAMESPACE = "knowledge-base"

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Executive summary of the analysis",
        },
        "key_findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of key findings from the analysis",
        },
        "metrics": {
            "type": "object",
            "description": "Key metrics and data points extracted",
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Actionable recommendations based on analysis",
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "Overall confidence level of the analysis",
        },
    },
    "required": ["summary", "key_findings", "recommendations", "confidence"],
}


# --- Tool Schemas ---

CALCULATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression. Supports basic arithmetic, "
            "sqrt, log, log10, sin, cos, tan, abs, round, pow, pi, e. "
            "Use for computing metrics, percentages, growth rates, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression to evaluate, e.g. '(150 - 120) / 120 * 100'",
                },
            },
            "required": ["expression"],
        },
    },
}

SEARCH_WEB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for current information using AI-grounded search. "
            "Returns a synthesized answer with citations. Use for real-time data, "
            "market trends, or topics requiring current information."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find information about",
                },
            },
            "required": ["query"],
        },
    },
}


# --- Helpers ---


def create_pinecone_store(namespace: str = DEFAULT_NAMESPACE, dimension: int | None = None):
    """Create PineconeStore if PINECONE_API_KEY is available, else None."""
    if not os.getenv("PINECONE_API_KEY"):
        return None

    try:
        from openbench.data.stores.pinecone import PineconeStore
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider

        return PineconeStore(
            index_name="openbench",
            namespace=namespace,
            embedding_provider=GoogleEmbeddingProvider(
                model="gemini-embedding-001", dimension=dimension
            ),
            create_if_missing=False,
        )
    except Exception as e:
        print(f"  Could not create PineconeStore: {e}")
        return None


def check_api_key():
    """Exit if GOOGLE_API_KEY is not set."""
    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY environment variable is required.")
        print("\nSet it with:")
        print("  export GOOGLE_API_KEY=your-api-key")
        sys.exit(1)


def setup_provider(model: str):
    """Configure GeminiLLMProvider as the default LLM provider."""
    configure_provider(
        name="gemini-default",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": os.getenv("GOOGLE_API_KEY")},
        settings={"model": model},
        is_default=True,
    )


def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(result):
    """Print ExecutionResult details."""
    print(f"\n  Status: {result.status}")
    print(f"  Iterations: {result.metadata.get('iterations', 'N/A')}")
    print(f"  Tools used: {result.metadata.get('tools_used', [])}")
    print(f"  Tokens: {result.tokens_used}")
    print(f"  Cost: ${result.cost:.6f}")
    print(f"\n--- Agent Response ---\n{result.output}\n")


# --- Tool Functions ---


def calculate(expression: str) -> str:
    """Evaluate a math expression using only allowed math functions.

    Sandboxed: __builtins__ disabled, only math functions exposed.
    Same pattern as gemini_agent_demo.py. Demo tool only.
    """
    allowed_names = {
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "pi": math.pi,
        "e": math.e,
        "abs": abs,
        "round": round,
        "pow": pow,
        "min": min,
        "max": max,
        "sum": sum,
    }
    try:
        # Sandboxed: builtins disabled, only math names allowed
        result = _safe_eval(expression, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


def _safe_eval(expression: str, allowed_names: dict) -> Any:
    """Sandboxed expression evaluator with no builtins access."""
    code = compile(expression, "<calc>", "eval")
    return eval(code, {"__builtins__": {}}, allowed_names)


def search_web(query: str) -> str:
    """Search the web using Gemini grounded search."""
    try:
        source = GroundedSearchSource(query=query, provider="gemini")
        result = source.extract()
        return result.content
    except Exception as e:
        return f"Web search failed: {e}"


# --- Demo Functions ---


def demo_analysis_tools(model: str, query: str):
    """Demo 1: AnalysisAgent + Tools.

    AnalysisAgent with calculate and search_web tools.
    The agent's reasoning loop decides which tools to use for analysis.
    Requires: GOOGLE_API_KEY
    """
    print_header("Demo 1: AnalysisAgent + Analysis Tools")

    print(f"\n  Model: {model}")
    print("  Agent: AnalysisAgent (statistical, trend_detection, comparison)")
    print("  Tools: calculate, search_web")
    print(f"  Query: {query}")

    agent = AnalysisAgent(
        goal=(
            "Analyze questions using data from web search and mathematical calculations. "
            "Use search_web to gather current data and statistics. "
            "Use calculate to compute metrics, growth rates, percentages, and comparisons. "
            "Provide data-driven analysis with specific numbers and calculations."
        ),
        methods=["statistical", "trend_detection", "comparison"],
        model=model,
        temperature=0.3,
        max_iterations=5,
    )

    agent.tools.register("calculate", calculate, schema=CALCULATE_SCHEMA)
    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent (reasoning loop)...\n")
    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


def demo_document_analysis(
    model: str,
    query: str,
    namespace: str = DEFAULT_NAMESPACE,
    dimension: int | None = None,
):
    """Demo 2: AnalysisAgent + RAG (Document Analysis).

    AnalysisAgent(store=PineconeStore) auto-retrieves documents for analysis.
    Also has search_web and calculate tools for enrichment.
    Requires: PINECONE_API_KEY + GOOGLE_API_KEY
    """
    print_header("Demo 2: AnalysisAgent + RAG (Document Analysis)")

    store = create_pinecone_store(namespace, dimension=dimension)
    if not store:
        print("\n  Skipped: PINECONE_API_KEY not set.")
        print("  Set it with: export PINECONE_API_KEY=your-key")
        return

    print(f"\n  Model: {model}")
    print(f"  Store: PineconeStore(namespace={namespace}) -- auto-retrieve")
    print("  Tools: calculate, search_web")
    print(f"  Query: {query}")

    agent = AnalysisAgent(
        goal=(
            "Analyze documents retrieved from the knowledge base. "
            "You will receive context from internal documents automatically. "
            "IMPORTANT: Always also use search_web to find current data "
            "for comparison and verification of the internal document data. "
            "Use calculate to compute metrics, trends, and comparisons. "
            "Cite sources: [Internal] for documents, [Web] for web results."
        ),
        methods=["statistical", "trend_detection", "comparison"],
        model=model,
        temperature=0.3,
        max_iterations=5,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.7,
    )

    agent.tools.register("calculate", calculate, schema=CALCULATE_SCHEMA)
    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent...\n")
    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


def demo_structured_output(model: str, query: str):
    """Demo 3: StructuredOutputAgent (JSON Output).

    StructuredOutputAgent returns analysis as validated JSON.
    The agent uses tools to gather data, then outputs structured results.
    First demo of StructuredOutputAgent in the codebase.
    Requires: GOOGLE_API_KEY
    """
    print_header("Demo 3: StructuredOutputAgent (JSON Analysis)")

    print(f"\n  Model: {model}")
    print("  Agent: StructuredOutputAgent (enforced JSON schema)")
    print("  Tools: search_web")
    print(f"  Schema: {list(ANALYSIS_SCHEMA['properties'].keys())}")
    print(f"  Query: {query}")

    agent = StructuredOutputAgent(
        goal=(
            "Analyze the given topic and return structured analysis results. "
            "Use search_web to gather current data and information. "
            "Provide a comprehensive analysis with specific findings and recommendations."
        ),
        output_schema=ANALYSIS_SCHEMA,
        model=model,
        temperature=0.3,
        max_iterations=5,
    )

    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent...\n")
    result = agent.execute(ExecutionContext(goal=query))

    # Print structured result
    print(f"\n  Status: {result.status}")
    print(f"  Iterations: {result.metadata.get('iterations', 'N/A')}")
    print(f"  Tools used: {result.metadata.get('tools_used', [])}")
    print(f"  Parsed: {result.metadata.get('parsed', False)}")
    print(f"  Tokens: {result.tokens_used}")
    print(f"  Cost: ${result.cost:.6f}")

    if result.metadata.get("parsed") and isinstance(result.output, dict):
        print("\n--- Structured Analysis (JSON) ---")
        print(json.dumps(result.output, indent=2, ensure_ascii=False))
    else:
        parse_error = result.metadata.get("parse_error", "")
        if parse_error:
            print(f"\n  Parse error: {parse_error}")
        print(f"\n--- Raw Response ---\n{result.output}\n")


# --- Main ---

DEFAULT_QUERIES = {
    "1": "What is the current global AI market size and projected growth rate? Compare top 3 AI companies by revenue.",
    "2": "Analyze the sustainability metrics and ESG performance from the indexed reports.",
    "3": "Analyze the current state of large language models: market leaders, pricing trends, and key differentiators.",
}


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Analysis Demo - AnalysisAgent + StructuredOutputAgent",
    )
    parser.add_argument(
        "--demo",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which demo to run (default: all)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--query",
        "-q",
        default=None,
        help="Custom query (default: demo-specific query)",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Pinecone namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=None,
        help="Embedding dimension override (default: provider native, e.g. 3072 for gemini-embedding-001)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Agentic Analysis Demo")
    print("=" * 60)
    print("\n  AnalysisAgent + StructuredOutputAgent")
    print(f"  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")
    print(f"  PINECONE_API_KEY: {'set' if os.getenv('PINECONE_API_KEY') else 'not set (optional)'}")

    check_api_key()
    setup_provider(args.model)

    try:
        if args.demo in ("1", "all"):
            demo_analysis_tools(args.model, args.query or DEFAULT_QUERIES["1"])

        if args.demo in ("2", "all"):
            demo_document_analysis(
                args.model,
                args.query or DEFAULT_QUERIES["2"],
                args.namespace,
                args.dimension,
            )

        if args.demo in ("3", "all"):
            demo_structured_output(args.model, args.query or DEFAULT_QUERIES["3"])

        print(f"\n{'=' * 60}")
        print("  Done!")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
