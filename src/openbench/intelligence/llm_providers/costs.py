"""Gemini per-1M-token pricing table (USD), used for cost estimation."""

from __future__ import annotations

# Cost per 1M tokens in USD (converted to per-1K for compatibility with config.py)
_GEMINI_COSTS: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    # Estimated (pricing page not yet mirrored here) — mirrors 3-flash-preview.
    "gemini-3.5-flash": {"input": 0.10, "output": 0.40},
}
