"""
Parallel Tool Execution Demo - Concurrent tool calls for faster agent execution.

Demonstrates how parallel_tool_execution=True enables BaseAgent to execute
multiple tool calls concurrently using ThreadPoolExecutor.

Two demos:
    1. ToolExecutor.execute_parallel: Direct parallel execution
    2. BaseAgent with parallel_tool_execution: Agent-driven concurrent tools

Usage:
    python examples/intelligence/parallel_tools_demo.py
    python examples/intelligence/parallel_tools_demo.py --demo 1
    python examples/intelligence/parallel_tools_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY (required for demo 2)
"""

import argparse
import os
import sys
import time

from openbench.intelligence.base import ToolExecutor

DEFAULT_MODEL = "gemini-2.5-flash"


# --- Mock Tools (with simulated latency) ---


def search_news(topic: str) -> str:
    """Search latest news about a topic (simulated with 0.5s latency)."""
    time.sleep(0.5)
    news = {
        "ai": "AI investments surpassed $200B globally in 2025. Major breakthroughs in reasoning.",
        "climate": "Global temperatures rose 1.5C above pre-industrial levels. COP31 set new targets.",
        "tech": "Quantum computing reached 1000 logical qubits. ARM dominates server market.",
        "markets": "S&P 500 reached 6500. Tech sector led gains. Interest rates at 3.5%.",
    }
    for key, value in news.items():
        if key in topic.lower():
            return value
    return f"No recent news found for '{topic}'."


def search_data(query: str) -> str:
    """Search company data (simulated with 0.5s latency)."""
    time.sleep(0.5)
    data = {
        "revenue": "Q4 2025 revenue: $12.5B (+18% YoY). Cloud: $4.2B. Services: $5.2B.",
        "headcount": "Total: 45,200 employees. Engineering: 18,500. Sales: 8,200.",
        "costs": "Operating costs: $8.7B. R&D: $2.1B. Infrastructure: $3.8B.",
        "forecast": "2026 guidance: Revenue $54-56B (+12-16%). Cloud growth 28-35%.",
    }
    for key, value in data.items():
        if key in query.lower():
            return value
    return f"No data found for '{query}'."


def calculate(a: float, b: float, operation: str = "add") -> str:
    """Perform a calculation (simulated with 0.3s latency).

    Args:
        a: First number.
        b: Second number.
        operation: One of 'add', 'subtract', 'multiply', 'divide', 'percentage'.
    """
    time.sleep(0.3)
    ops = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else float("inf"),
        "percentage": (a / b * 100) if b != 0 else float("inf"),
    }
    result = ops.get(operation)
    if result is None:
        return f"Unknown operation: {operation}"
    return f"{result:.4f}"


def get_weather(city: str) -> str:
    """Get weather for a city (simulated with 0.4s latency)."""
    time.sleep(0.4)
    weather = {
        "tokyo": "Tokyo: 12C, Partly cloudy, Humidity 55%",
        "london": "London: 8C, Rainy, Humidity 80%",
        "new york": "New York: 5C, Clear, Humidity 40%",
        "jakarta": "Jakarta: 31C, Thunderstorms, Humidity 85%",
    }
    return weather.get(city.lower(), f"Weather data not available for {city}")


# --- Setup ---


def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# --- Demo Functions ---


def demo_executor_parallel():
    """Demo 1: ToolExecutor.execute_parallel direct usage.

    Shows the performance difference between sequential and parallel
    tool execution when multiple tools are called at once.
    """
    print_header("Demo 1: ToolExecutor Sequential vs Parallel")

    executor = ToolExecutor()
    executor.register("search_news", search_news, description="Search news")
    executor.register("search_data", search_data, description="Search company data")
    executor.register("calculate", calculate, description="Math calculation")
    executor.register("get_weather", get_weather, description="Get weather")

    calls = [
        {"name": "search_news", "id": "call_1", "arguments": {"topic": "AI"}},
        {"name": "search_data", "id": "call_2", "arguments": {"query": "revenue"}},
        {
            "name": "calculate",
            "id": "call_3",
            "arguments": {"a": 12.5, "b": 8.7, "operation": "subtract"},
        },
        {"name": "get_weather", "id": "call_4", "arguments": {"city": "Tokyo"}},
    ]

    print(f"\n  Executing {len(calls)} tool calls...")
    print(f"  Tools: {[c['name'] for c in calls]}")
    print("  Simulated latency: 0.3-0.5s per tool")

    # Sequential execution
    print("\n  --- Sequential ---")
    start = time.time()
    seq_results = []
    for call in calls:
        result = executor.execute(call["name"], **call["arguments"])
        seq_results.append(result)
    seq_time = time.time() - start
    print(f"  Time: {seq_time:.2f}s")
    for call, result in zip(calls, seq_results, strict=False):
        print(f"    [{call['name']}] {str(result)[:70]}")

    # Parallel execution
    print("\n  --- Parallel ---")
    start = time.time()
    par_results = executor.execute_parallel(calls)
    par_time = time.time() - start
    print(f"  Time: {par_time:.2f}s")
    for r in par_results:
        status = "OK" if r["error"] is None else f"ERR: {r['error']}"
        result_str = str(r["result"])[:70] if r["result"] else "None"
        print(f"    [{r['call']['name']}] ({status}) {result_str}")

    # Comparison
    speedup = seq_time / par_time if par_time > 0 else 0
    print("\n  --- Comparison ---")
    print(f"  Sequential: {seq_time:.2f}s")
    print(f"  Parallel:   {par_time:.2f}s")
    print(f"  Speedup:    {speedup:.1f}x")


def demo_executor_error_handling():
    """Demo 1b: Parallel execution with error handling.

    Shows that one tool failure doesn't block other tools.
    """
    print_header("Demo 1b: Error Handling in Parallel Execution")

    def flaky_tool(x: int) -> str:
        """Tool that fails on even numbers."""
        time.sleep(0.3)
        if x % 2 == 0:
            msg = f"Cannot process even number: {x}"
            raise ValueError(msg)
        return f"Processed: {x}"

    executor = ToolExecutor()
    executor.register("flaky_tool", flaky_tool, description="Flaky tool")

    calls = [{"name": "flaky_tool", "id": f"call_{i}", "arguments": {"x": i}} for i in range(1, 5)]

    print(f"\n  Executing {len(calls)} calls (even numbers will fail)...")
    results = executor.execute_parallel(calls)

    for r in results:
        x = r["call"]["arguments"]["x"]
        if r["error"]:
            print(f"    x={x}: FAILED - {r['error']}")
        else:
            print(f"    x={x}: OK - {r['result']}")

    successes = sum(1 for r in results if r["error"] is None)
    failures = sum(1 for r in results if r["error"] is not None)
    print(f"\n  Results: {successes} succeeded, {failures} failed")
    print("  (failures don't block other tools)")


def demo_agent_parallel(model: str):
    """Demo 2: BaseAgent with parallel_tool_execution=True.

    Shows how the agent's reasoning loop executes multiple tool calls
    concurrently when the LLM requests them in a single turn.
    """
    print_header("Demo 2: BaseAgent with Parallel Tools")

    if not os.getenv("GOOGLE_API_KEY"):
        print("\n  Skipped: GOOGLE_API_KEY not set.")
        print("  Set it with: export GOOGLE_API_KEY=your-key")
        return

    from openbench.core.abstractions import ExecutionContext
    from openbench.core.providers import ProviderType, configure_provider
    from openbench.intelligence.base import BaseAgent
    from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

    configure_provider(
        name="gemini-default",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": os.getenv("GOOGLE_API_KEY")},
        settings={"model": model},
        is_default=True,
    )

    query = (
        "I need a briefing that covers: current AI news, our company's revenue data, "
        "and the weather in Tokyo. Gather all the information and summarize."
    )

    tools = [search_news, search_data, get_weather]

    # Without parallel (sequential)
    print(f"\n  Model: {model}")
    print(f"  Query: {query[:80]}...")
    print(f"  Tools: {[t.__name__ for t in tools]}")

    print("\n  --- Sequential Tool Execution ---")
    agent_seq = BaseAgent(
        goal="Gather and summarize information from multiple sources.",
        model=model,
        tools=tools,
        temperature=0.3,
        max_iterations=5,
        parallel_tool_execution=False,
    )

    start = time.time()
    result_seq = agent_seq.execute(ExecutionContext(goal=query))
    seq_time = time.time() - start

    print(f"  Time: {seq_time:.2f}s")
    print(f"  Iterations: {result_seq.metadata.get('iterations', 'N/A')}")
    print(f"  Tools used: {result_seq.metadata.get('tools_used', [])}")
    print(f"  Tokens: {result_seq.tokens_used}")
    print(f"\n--- Response ---\n{result_seq.output[:300]}...\n")

    # With parallel
    print("  --- Parallel Tool Execution ---")
    agent_par = BaseAgent(
        goal="Gather and summarize information from multiple sources.",
        model=model,
        tools=tools,
        temperature=0.3,
        max_iterations=5,
        parallel_tool_execution=True,
    )

    start = time.time()
    result_par = agent_par.execute(ExecutionContext(goal=query))
    par_time = time.time() - start

    print(f"  Time: {par_time:.2f}s")
    print(f"  Iterations: {result_par.metadata.get('iterations', 'N/A')}")
    print(f"  Tools used: {result_par.metadata.get('tools_used', [])}")
    print(f"  Tokens: {result_par.tokens_used}")
    print(f"\n--- Response ---\n{result_par.output[:300]}...\n")

    # Comparison
    if par_time > 0:
        speedup = seq_time / par_time
        print("  --- Comparison ---")
        print(f"  Sequential: {seq_time:.2f}s")
        print(f"  Parallel:   {par_time:.2f}s")
        print(f"  Speedup:    {speedup:.1f}x")
        print(
            "\n  Note: Actual speedup depends on whether the LLM requests"
            "\n  multiple tools in a single turn (model-dependent behavior)."
        )


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Parallel Tool Execution Demo - Concurrent tool calls",
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
    print("  OpenBench: Parallel Tool Execution Demo")
    print("=" * 60)
    print(f"\n  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'not set (optional)'}")

    try:
        if args.demo in ("1", "all"):
            demo_executor_parallel()
            demo_executor_error_handling()

        if args.demo in ("2", "all"):
            demo_agent_parallel(args.model)

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
