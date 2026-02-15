"""
Task Planning Demo - LLM-based task decomposition before agent execution.

Demonstrates how TaskPlanner breaks complex goals into step-by-step plans
that guide the agent's reasoning loop.

Two modes:
    1. Standalone: Use TaskPlanner directly to see plans
    2. With BaseAgent: Enable enable_planning=True for automatic planning

Usage:
    python examples/intelligence/planning_demo.py
    python examples/intelligence/planning_demo.py --demo 1
    python examples/intelligence/planning_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY (required)
"""

import argparse
import os
import sys
from typing import Any

from openbench.core.abstractions import ExecutionContext
from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent
from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

DEFAULT_MODEL = "gemini-2.5-flash"


# --- Mock Tools ---

KNOWLEDGE_BASE: dict[str, str] = {
    "revenue": (
        "Q4 2025 total revenue: $12.5B (+18% YoY). Cloud division: $4.2B (+32%). "
        "Hardware division: $3.1B (+5%). Services division: $5.2B (+15%)."
    ),
    "costs": (
        "Q4 2025 operating costs: $8.7B. R&D spending: $2.1B (17% of revenue). "
        "Marketing: $1.4B. Infrastructure: $3.8B. Personnel: $1.4B."
    ),
    "headcount": (
        "Total employees: 45,200 (up from 42,800 in Q3). Engineering: 18,500. "
        "Sales: 8,200. Operations: 12,000. Management: 6,500."
    ),
    "forecast": (
        "2026 guidance: Revenue $54-56B (+12-16%). Cloud expected to grow 28-35%. "
        "Capex planned at $8B for AI infrastructure expansion."
    ),
}


def search_data(topic: str) -> str:
    """Search the company knowledge base for information."""
    topic_lower = topic.lower()
    for key, value in KNOWLEDGE_BASE.items():
        if key in topic_lower:
            return value
    return "No data found for the given topic."


def calculate(a: float, b: float, operation: str = "add") -> str:
    """Perform a calculation on two numbers.

    Args:
        a: First number.
        b: Second number.
        operation: One of 'add', 'subtract', 'multiply', 'divide', 'percentage'.
    """
    ops = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else float("inf"),
        "percentage": (a / b * 100) if b != 0 else float("inf"),
    }
    result = ops.get(operation)
    if result is None:
        return f"Unknown operation: {operation}. Use: add, subtract, multiply, divide, percentage."
    return f"{result:.4f}"


def format_report(title: str, content: str) -> str:
    """Format content into a structured report section."""
    return f"## {title}\n\n{content}\n"


# --- Setup ---


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


# --- Demo Functions ---


def demo_standalone(model: str):
    """Demo 1: Standalone TaskPlanner.

    Shows how TaskPlanner decomposes complex goals into structured plans
    with steps, estimated tools, and reasoning.
    """
    print_header("Demo 1: Standalone TaskPlanner")

    from openbench.core.providers import get_provider_service
    from openbench.intelligence.planning import TaskPlanner

    service = get_provider_service()
    llm = service.resolve(ProviderType.LLM)

    planner = TaskPlanner(llm, model=model)

    goals = [
        (
            "Analyze Q4 revenue trends and compare with Q3 performance",
            ["search_data", "calculate"],
        ),
        (
            "Create a comprehensive financial report with cost analysis and forecasts",
            ["search_data", "calculate", "format_report"],
        ),
        (
            "Summarize the current state of the company",
            [],  # No tools available
        ),
    ]

    for goal, tools in goals:
        print(f"\n  Goal: {goal}")
        print(f"  Available tools: {tools or 'none'}")

        plan = planner.plan(goal, tools if tools else None)

        print(f"\n  Reasoning: {plan.reasoning}")
        print(f"  Estimated tools: {plan.estimated_tools}")
        print("  Steps:")
        for i, step in enumerate(plan.steps, 1):
            print(f"    {i}. {step}")

        # Show formatted prompt
        formatted = planner.format_plan_prompt(plan)
        print(f"\n  Formatted prompt:\n    {formatted.replace(chr(10), chr(10) + '    ')}")


def demo_agent_with_planning(model: str):
    """Demo 2: BaseAgent with enable_planning=True.

    BaseAgent first decomposes the goal into a plan, then executes it
    step-by-step using the reasoning loop with tool calls.
    """
    print_header("Demo 2: BaseAgent with Planning")

    tools: list[Any] = [search_data, calculate, format_report]

    # Without planning (baseline)
    print("\n  --- Without Planning ---")
    agent_baseline = BaseAgent(
        goal="Analyze the company's financial performance",
        model=model,
        tools=tools,
        temperature=0.3,
        max_iterations=8,
        enable_planning=False,
    )

    query = (
        "What is the revenue breakdown by division, and how does the cost structure "
        "compare? Calculate the profit margin."
    )
    print(f"  Query: {query}\n")
    result_baseline = agent_baseline.execute(ExecutionContext(goal=query))
    print_result(result_baseline)

    # With planning
    print("  --- With Planning ---")
    agent_planned = BaseAgent(
        goal="Analyze the company's financial performance",
        model=model,
        tools=tools,
        temperature=0.3,
        max_iterations=8,
        enable_planning=True,
    )

    print(f"  Query: {query}")
    print("  (agent will first create a plan, then execute step by step)\n")
    result_planned = agent_planned.execute(ExecutionContext(goal=query))
    print_result(result_planned)

    # Compare
    print("  --- Comparison ---")
    baseline_iters = result_baseline.metadata.get("iterations", 0)
    planned_iters = result_planned.metadata.get("iterations", 0)
    print(f"  Without planning: {baseline_iters} iterations, {result_baseline.tokens_used} tokens")
    print(f"  With planning:    {planned_iters} iterations, {result_planned.tokens_used} tokens")


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Task Planning Demo - LLM-based task decomposition",
    )
    parser.add_argument(
        "--demo",
        choices=["1", "2", "all"],
        default="all",
        help="Which demo to run (default: all)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Task Planning Demo")
    print("=" * 60)
    print(f"\n  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")

    check_api_key()
    setup_provider(args.model)

    try:
        if args.demo in ("1", "all"):
            demo_standalone(args.model)

        if args.demo in ("2", "all"):
            demo_agent_with_planning(args.model)

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
