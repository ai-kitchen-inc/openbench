"""
Real Gemini-powered agent for the chat demo.

Uses BaseAgent with GeminiLLMProvider + tools (calculator, knowledge base, datetime).
Supports multi-turn conversation with memory.

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install google-genai
"""

import math
import os
from datetime import datetime
from typing import Any

from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent


# ── Knowledge base (same as gemini_agent_demo.py) ──

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


# ── Tool schemas (explicit for Gemini) ──

CALCULATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression. "
            "Supports: +, -, *, /, **, sqrt, log, sin, cos, pi, e."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression, e.g. '2 * 3 + 1' or 'sqrt(144)'",
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
            "Topics: renewable_energy (solar, wind, storage), "
            "ai_trends (models, agents, regulation), "
            "market_data (tech_stocks, venture_capital)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "One of: renewable_energy, ai_trends, market_data",
                },
                "subtopic": {
                    "type": "string",
                    "description": "Subtopic within the topic (optional)",
                },
            },
            "required": ["topic"],
        },
    },
}

GET_DATETIME_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_datetime",
        "description": "Get the current date and time.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


# ── Tool functions ──

# NOTE: calculate() uses a sandboxed eval with __builtins__ disabled and only
# math functions allowed. This is the same pattern used in the official
# gemini_agent_demo.py. Safe for demo use only.
_MATH_NAMESPACE = {
    "__builtins__": {},
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": math.pi, "e": math.e, "abs": abs, "round": round, "pow": pow,
}


def calculate(expression: str) -> str:
    """Evaluate a math expression using sandboxed math functions."""
    try:
        result = eval(expression, _MATH_NAMESPACE)  # noqa: S307 — sandboxed, no builtins
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def knowledge_lookup(topic: str, subtopic: str = "") -> str:
    """Look up information from the knowledge base."""
    topic_data = KNOWLEDGE_BASE.get(topic)
    if not topic_data:
        available = ", ".join(KNOWLEDGE_BASE.keys())
        return f"Topic '{topic}' not found. Available: {available}"
    if subtopic:
        info = topic_data.get(subtopic)
        if not info:
            available = ", ".join(topic_data.keys())
            return f"Subtopic '{subtopic}' not found. Available: {available}"
        return info
    return "\n\n".join(f"[{sub}] {info}" for sub, info in topic_data.items())


def get_datetime() -> str:
    """Get current date and time."""
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y at %H:%M:%S")


# ── Agent factory ──


def create_gemini_agent(
    model: str = "gemini-3-flash-preview",
    temperature: float = 0.7,
) -> BaseAgent:
    """Create a BaseAgent powered by Gemini with tools.

    Requires GOOGLE_API_KEY environment variable.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    # Configure Gemini as default LLM provider
    configure_provider(
        name="gemini-chat-demo",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": api_key},
        settings={"model": model},
        is_default=True,
    )

    # Create agent with tools
    agent = BaseAgent(
        goal=(
            "You are a helpful AI assistant. Answer questions, perform calculations, "
            "and look up information from the knowledge base when relevant. "
            "Be concise and informative. Use markdown formatting."
        ),
        model=model,
        temperature=temperature,
        max_iterations=5,
        system_prompt=(
            "You are an AI assistant powered by OpenBench. "
            "You have access to tools: calculator, knowledge base, and datetime. "
            "Use the knowledge_lookup tool when users ask about renewable energy, "
            "AI trends, or market data. Use calculate for math. "
            "Always respond in clear, well-formatted markdown."
        ),
    )

    # Register tools with explicit schemas
    agent.tools.register("calculate", calculate, schema=CALCULATE_SCHEMA)
    agent.tools.register("knowledge_lookup", knowledge_lookup, schema=KNOWLEDGE_LOOKUP_SCHEMA)
    agent.tools.register("get_datetime", get_datetime, schema=GET_DATETIME_SCHEMA)

    return agent
