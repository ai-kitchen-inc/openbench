"""Tools for the web-search SDK skill.

Wraps ``openbench.data.sources.grounded_search.GroundedSearchSource``
into agent-callable tools. The heavy lifting (Gemini grounding API,
source extraction, redirect resolution) is already done by the data
source — this module just provides the tool interface + schemas.

Imports are lazy so the skill loads without ``[google]`` or ``[search]``
extras. The error surfaces at tool call time, not at skill discovery.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "web_search",
    "web_search_multi",
    "WEB_SEARCH_SCHEMA",
    "WEB_SEARCH_MULTI_SCHEMA",
]


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _do_search(
    query: str,
    provider: str = "gemini",
    model: str | None = None,
) -> dict[str, Any]:
    """Execute a single grounded search and return a normalized result.

    Returns:
        {"query": str, "answer": str, "sources": [{"title", "url"}, ...]}
        or {"error": str} on failure.
    """
    try:
        from openbench.data.sources.grounded_search import GroundedSearchSource
    except ImportError:
        return _error(
            "google-genai is required for web search. Install with: pip install openbench[google]"
        )

    try:
        source = GroundedSearchSource(
            query=query,
            provider=provider,
            model=model,
        )
        source.validate()
        result = source.extract()
    except Exception as e:
        return _error(f"Search failed: {e}")

    # Normalize the result into a clean tool-return shape.
    # GroundedSearchSource.extract() returns RawData; the actual
    # search result is in the metadata populated during extraction.
    content = result.content if hasattr(result, "content") else str(result)
    metadata = result.metadata if hasattr(result, "metadata") else {}
    sources = metadata.get("sources", [])

    # Filter to only web sources (skip search_suggestion entries)
    web_sources = [
        {"title": s.get("title", ""), "url": s.get("url", "")}
        for s in sources
        if isinstance(s, dict) and s.get("url")
    ]

    return {
        "query": query,
        "answer": str(content),
        "sources": web_sources,
        "source_count": len(web_sources),
    }


# ---------------------------------------------------------------------------
# web_search — single query
# ---------------------------------------------------------------------------


def web_search(
    query: str,
    provider: str = "gemini",
) -> dict[str, Any]:
    """Search the web for real-time information.

    Uses Gemini's built-in Google Search grounding to return a
    synthesized answer with source citations. Use this when you
    need up-to-date facts, recent publications, or external context
    that is not in the uploaded files or skill references.

    Args:
        query: The search query. Be specific and factual.
        provider: Search provider (default "gemini").

    Returns:
        Dict with query, answer (synthesized text), sources (list of
        {title, url} dicts), and source_count.
    """
    if not query or not query.strip():
        return _error("query cannot be empty")
    return _do_search(query=query.strip(), provider=provider)


# ---------------------------------------------------------------------------
# web_search_multi — batch queries
# ---------------------------------------------------------------------------


def web_search_multi(
    queries: list[str],
    provider: str = "gemini",
) -> dict[str, Any]:
    """Search the web for multiple queries in one call.

    Each query is executed independently. Use this when you need to
    gather information from several angles before synthesizing a
    response (e.g. search for a standard AND its latest amendment).

    Args:
        queries: List of search query strings.
        provider: Search provider (default "gemini").

    Returns:
        Dict with results (list of per-query results) and
        total_sources count.
    """
    if not isinstance(queries, list) or not queries:
        return _error("`queries` must be a non-empty list of strings")

    results: list[dict[str, Any]] = []
    total_sources = 0
    for q in queries:
        if not isinstance(q, str) or not q.strip():
            results.append(_error(f"invalid query: {q!r}"))
            continue
        r = _do_search(query=q.strip(), provider=provider)
        results.append(r)
        if "error" not in r:
            total_sources += r.get("source_count", 0)

    return {
        "results": results,
        "query_count": len(queries),
        "total_sources": total_sources,
    }


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


WEB_SEARCH_SCHEMA = _schema(
    "web_search",
    "Search the web for real-time information using Google Search grounding. "
    "Returns a synthesized answer with source citations. Use when you need "
    "up-to-date facts, recent publications, regulation updates, or external "
    "context not available in uploaded files or skill references. "
    "Be specific in your query — include dates, standards numbers, or "
    "exact topics for best results.",
    {
        "query": {
            "type": "string",
            "description": (
                "The search query. Be specific and factual. "
                'E.g. "ISO 14040 latest amendment 2026" or '
                '"Indonesia PROPER 2025 gold criteria"'
            ),
        },
        "provider": {
            "type": "string",
            "description": "Search provider. Default 'gemini'.",
            "enum": ["gemini", "perplexity"],
        },
    },
    ["query"],
)

WEB_SEARCH_MULTI_SCHEMA = _schema(
    "web_search_multi",
    "Search the web for multiple queries in one call. Each query runs "
    "independently. Use when you need to gather information from several "
    "angles before synthesizing (e.g. search for a standard AND its "
    "latest amendment AND regional adoption status).",
    {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of search queries.",
        },
        "provider": {
            "type": "string",
            "description": "Search provider. Default 'gemini'.",
            "enum": ["gemini", "perplexity"],
        },
    },
    ["queries"],
)
