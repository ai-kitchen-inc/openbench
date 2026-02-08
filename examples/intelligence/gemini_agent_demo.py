"""
Gemini Agent Demo - BaseAgent with GeminiLLMProvider

First example that runs BaseAgent.execute() with the reasoning loop,
tool calling, and multi-turn memory using GeminiLLMProvider.

Three demo patterns:
    1. Direct LLM: Call GeminiLLMProvider.generate() directly
    2. Agent + Tools: BaseAgent with tool calling (reasoning loop)
    3. Multi-turn: Agent with memory persistence across turns

Usage:
    # Run all demos
    python gemini_agent_demo.py

    # Run specific demo
    python gemini_agent_demo.py --demo 2

    # Use different model
    python gemini_agent_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install google-genai
"""

import argparse
import math
import os
import sys
from typing import Any

# Trigger LLMProviderRegistry registration (import side-effect)
from openbench.core.abstractions import ExecutionContext
from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent

# OpenBench imports
from openbench.intelligence.llm_providers import GeminiLLMProvider

# --- Constants ---

DEFAULT_MODEL = "gemini-2.5-flash"

KNOWLEDGE_BASE: dict[str, dict[str, str]] = {
    "renewable_energy": {
        "solar": (
            "Global solar capacity reached 1.6 TW in 2025. Average cost dropped to "
            "$0.03/kWh. China leads with 600 GW installed. Perovskite solar cells "
            "achieved 33% efficiency in lab settings."
        ),
        "wind": (
            "Offshore wind capacity grew 35% YoY in 2025. Largest turbine is 18 MW. "
            "Europe leads offshore with 45 GW total. Floating wind farms emerging "
            "in deep water locations."
        ),
        "storage": (
            "Battery storage costs fell to $100/kWh in 2025. Sodium-ion batteries "
            "entering market at 30% lower cost than lithium. Grid-scale storage "
            "deployments doubled to 120 GWh globally."
        ),
    },
    "ai_trends": {
        "models": (
            "Frontier models surpassed 10T parameters in 2025. Mixture-of-experts "
            "architectures dominate. Open-source models closing gap with proprietary. "
            "Multi-modal capabilities now standard."
        ),
        "agents": (
            "AI agent frameworks grew 400% in adoption during 2025. Key players: "
            "LangChain, CrewAI, Google ADK, AutoGen. Tool use and reasoning loops "
            "became production-ready. Orchestration platforms emerging."
        ),
        "regulation": (
            "EU AI Act enforcement began in 2025. US executive order on AI safety "
            "expanded. China released AI governance framework. Industry self-regulation "
            "through voluntary commitments."
        ),
    },
    "market_data": {
        "tech_stocks": (
            "NASDAQ up 18% YTD in 2025. AI-related stocks outperformed by 2x. "
            "Semiconductor companies saw record revenue. Cloud providers grew 25% "
            "on AI infrastructure demand."
        ),
        "venture_capital": (
            "Global VC funding reached $350B in 2025. AI startups captured 40% "
            "of total funding. Average Series A rose to $15M. Key sectors: "
            "AI agents, climate tech, biotech."
        ),
    },
}


# --- Tool Schemas (explicit for Gemini) ---

CALCULATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression and return the result. "
            "Supports basic arithmetic (+, -, *, /), exponents (**), "
            "and common functions (sqrt, log, sin, cos, pi, e)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate, e.g. '2 * 3 + 1'",
                },
            },
            "required": ["expression"],
        },
    },
}

KNOWLEDGE_LOOKUP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "knowledge_lookup",
        "description": (
            "Look up information from the knowledge base. "
            "Available topics: renewable_energy, ai_trends, market_data. "
            "Each topic has subtopics (e.g., renewable_energy has solar, wind, storage)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Main topic to look up. One of: renewable_energy, ai_trends, market_data"
                    ),
                },
                "subtopic": {
                    "type": "string",
                    "description": (
                        "Specific subtopic within the topic. "
                        "E.g., 'solar' for renewable_energy, 'models' for ai_trends"
                    ),
                },
            },
            "required": ["topic"],
        },
    },
}


# --- Tool Functions ---


def calculate(expression: str) -> str:
    """Evaluate a math expression using only allowed math functions.

    Sandboxed: __builtins__ disabled, only math functions exposed.
    This is a demo tool — not for production use.
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
    }
    try:
        # Sandboxed eval: builtins disabled, only math names allowed
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


def knowledge_lookup(topic: str, subtopic: str = "") -> str:
    """Look up information from the knowledge base."""
    topic_data = KNOWLEDGE_BASE.get(topic)
    if not topic_data:
        available = ", ".join(KNOWLEDGE_BASE.keys())
        return f"Topic '{topic}' not found. Available topics: {available}"

    if subtopic:
        info = topic_data.get(subtopic)
        if not info:
            available = ", ".join(topic_data.keys())
            return f"Subtopic '{subtopic}' not found in {topic}. Available: {available}"
        return info

    # Return all subtopics
    parts = [f"[{sub}] {info}" for sub, info in topic_data.items()]
    return "\n\n".join(parts)


# --- Helpers ---


def check_api_key():
    """Check that GOOGLE_API_KEY is set."""
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


def demo_direct_llm(model: str):
    """Demo 1: Direct LLM call without BaseAgent.

    Simplest usage — call GeminiLLMProvider.generate() directly.
    No tools, no reasoning loop, just a single LLM call.
    """
    print_header("Demo 1: Direct LLM Call")

    api_key = os.getenv("GOOGLE_API_KEY")
    llm = GeminiLLMProvider(api_key=api_key, model=model)

    print(f"\n  Model: {model}")
    print("  Prompt: 'Explain the difference between AI agents and AI workflows in 3 sentences.'")
    print("\n  Calling GeminiLLMProvider.generate()...\n")

    response = llm.generate(
        prompt="Explain the difference between AI agents and AI workflows in 3 sentences.",
        model=model,
        temperature=0.3,
    )

    print(f"--- Response ---\n{response.text}\n")
    print(f"  Model: {response.model}")
    print(f"  Tokens: {response.tokens_used}")
    print(f"  Cost: ${response.cost:.6f}")

    # Also show conversation-style (as BaseAgent would use it)
    print("\n  --- Conversation-style call ---")
    messages = [
        {"role": "system", "content": "You are a concise technical writer."},
        {"role": "user", "content": "What is OpenBench? Answer in one sentence."},
    ]

    response2 = llm.generate(prompt=messages, model=model, temperature=0.3)
    print(f"  Response: {response2.text}")
    print(f"  Tokens: {response2.tokens_used}")


def demo_agent_with_tools(model: str):
    """Demo 2: BaseAgent with tool calling (reasoning loop).

    BaseAgent uses GeminiLLMProvider to:
    1. Understand the goal
    2. Decide which tools to call
    3. Execute tools and process results
    4. Iterate until done
    """
    print_header("Demo 2: BaseAgent + Tool Calling")

    setup_provider(model)

    print(f"\n  Model: {model}")
    print("  Tools: calculate, knowledge_lookup")
    print("  Max iterations: 5")

    # Create agent
    agent = BaseAgent(
        goal="Research and analyze topics using available tools",
        model=model,
        temperature=0.3,
        max_iterations=5,
    )

    # Register tools with explicit schemas (auto-generated schemas have empty properties)
    agent.tools.register("calculate", calculate, schema=CALCULATE_SCHEMA)
    agent.tools.register("knowledge_lookup", knowledge_lookup, schema=KNOWLEDGE_LOOKUP_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")

    # Execute with a goal that requires tool use
    print("\n  Executing agent...\n")
    context = ExecutionContext(
        goal=(
            "Look up the latest information about renewable energy (solar and storage), "
            "then calculate the cost savings if solar costs dropped another 20% from $0.03/kWh. "
            "Summarize your findings."
        ),
    )

    result = agent.execute(context)
    print_result(result)


def demo_multi_turn(model: str):
    """Demo 3: Multi-turn conversation with memory.

    Shows that BaseAgent preserves memory across execute() calls,
    allowing follow-up questions. Also demonstrates agent.reset().
    """
    print_header("Demo 3: Multi-Turn Conversation")

    setup_provider(model)

    print(f"\n  Model: {model}")
    print("  Tools: knowledge_lookup")
    print("  Showing: memory persistence + reset\n")

    agent = BaseAgent(
        goal="Answer questions about technology trends using the knowledge base",
        model=model,
        temperature=0.3,
        max_iterations=5,
    )

    agent.tools.register("knowledge_lookup", knowledge_lookup, schema=KNOWLEDGE_LOOKUP_SCHEMA)

    # Turn 1: Initial question
    print("--- Turn 1: Initial Question ---")
    result1 = agent.execute(
        ExecutionContext(
            goal="What are the latest AI agent trends? Use the knowledge base.",
        )
    )
    print(f"  Status: {result1.status}")
    print(f"  Iterations: {result1.metadata.get('iterations')}")
    print(f"  Response: {(result1.output or '')[:200]}...")
    print(f"  Memory messages: {len(agent.memory.messages)}")

    # Turn 2: Follow-up (agent has memory of Turn 1)
    print("\n--- Turn 2: Follow-up (memory preserved) ---")
    result2 = agent.execute(
        ExecutionContext(
            goal=(
                "Based on what you just found, how does VC funding relate to the AI agent growth? "
                "Look up market_data venture_capital for context."
            ),
        )
    )
    print(f"  Status: {result2.status}")
    print(f"  Iterations: {result2.metadata.get('iterations')}")
    print(f"  Response: {(result2.output or '')[:200]}...")
    print(f"  Memory messages: {len(agent.memory.messages)}")

    # Reset and start fresh
    print("\n--- After Reset ---")
    agent.reset()
    print(f"  Memory messages after reset: {len(agent.memory.messages)}")

    # Turn 3: New question after reset (no prior context)
    result3 = agent.execute(
        ExecutionContext(
            goal="What is the current state of battery storage? Look it up.",
        )
    )
    print(f"  Status: {result3.status}")
    print(f"  Iterations: {result3.metadata.get('iterations')}")
    print(f"  Response: {(result3.output or '')[:200]}...")

    # Summary
    total_tokens = (
        (result1.tokens_used or 0) + (result2.tokens_used or 0) + (result3.tokens_used or 0)
    )
    total_cost = result1.cost + result2.cost + result3.cost
    print(f"\n  Total tokens (3 turns): {total_tokens}")
    print(f"  Total cost (3 turns): ${total_cost:.6f}")


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Gemini Agent Demo - BaseAgent with GeminiLLMProvider",
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
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Gemini Agent Demo")
    print("=" * 60)
    print("\n  GeminiLLMProvider + BaseAgent reasoning loop")
    print(f"  Model: {args.model}")

    check_api_key()

    try:
        demos = args.demo

        if demos in ("1", "all"):
            demo_direct_llm(args.model)

        if demos in ("2", "all"):
            demo_agent_with_tools(args.model)

        if demos in ("3", "all"):
            demo_multi_turn(args.model)

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
