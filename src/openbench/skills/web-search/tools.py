"""Tools for the web-search SDK skill.

Wraps ``openbench.data.sources.grounded_search.GroundedSearchSource``
into agent-callable tools. The heavy lifting (Gemini grounding API,
source extraction, redirect resolution) is already done by the data
source — this module just provides the tool interface + schemas.

Imports are lazy so the skill loads without ``[google]`` or ``[search]``
extras. The error surfaces at tool call time, not at skill discovery.
"""

from __future__ import annotations

import html as _html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "web_search",
    "web_search_multi",
    "fetch_url",
    "WEB_SEARCH_SCHEMA",
    "WEB_SEARCH_MULTI_SCHEMA",
    "FETCH_URL_SCHEMA",
]

_FETCH_TIMEOUT_SECONDS = 20.0
_FETCH_MAX_BYTES = 2 * 1024 * 1024
_FETCH_DEFAULT_MAX_CHARS = 20_000
_FETCH_MAX_MAX_CHARS = 100_000
_FETCH_USER_AGENT = "OpenBench-WebSearch/0.1"

# Content types returned as raw decoded text (no HTML cleanup).
_FETCH_RAW_TEXT_TYPES = {"application/json", "application/xml", "application/rss+xml"}


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
# fetch_url — read one specific web page
# ---------------------------------------------------------------------------


def _validate_public_http_url(url: str) -> str:
    """Return the stripped URL, or raise ValueError for unsafe targets.

    SSRF guard for agent-triggered fetches: only http(s), and every
    address the hostname resolves to must be publicly routable —
    loopback, RFC1918, link-local (incl. cloud metadata 169.254.x),
    reserved, multicast, and unspecified addresses are all refused.
    """
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be a valid http or https URL.")
    try:
        resolved = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {parsed.hostname!r}.") from exc
    for entry in resolved:
        ip = ipaddress.ip_address(entry[4][0])
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(
                "URL resolves to a private or local address and cannot be fetched."
            )
    return value


class _ReadableHTMLParser(HTMLParser):
    """Minimal readable-text extractor (mirrors general-chat's parser)."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg"}
    _BLOCK_TAGS = {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def _clean_html_text(raw_html: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(raw_html)
    text = _html.unescape(" ".join(parser.parts))
    return re.sub(r"\n\s*\n\s*", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _extract_html_title(raw_html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = _html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title or None


def fetch_url(url: str, max_chars: int = _FETCH_DEFAULT_MAX_CHARS) -> dict[str, Any]:
    """Fetch one web page and return its readable text content.

    Use when the user shares a specific URL and asks to read, extract,
    or summarize that exact page. For open-ended questions use
    ``web_search`` instead.

    Args:
        url: The http(s) URL to fetch. Private/local addresses are refused.
        max_chars: Maximum characters of extracted text to return.

    Returns:
        Dict with url, final_url, title, content_type, status_code,
        text, text_chars, truncated — or {"error": str} on failure.
    """
    if not url or not str(url).strip():
        return _error("url cannot be empty")
    try:
        validated = _validate_public_http_url(str(url))
    except ValueError as exc:
        return _error(str(exc))
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = _FETCH_DEFAULT_MAX_CHARS
    max_chars = max(1, min(max_chars, _FETCH_MAX_MAX_CHARS))

    import requests

    try:
        response = requests.get(
            validated,
            timeout=_FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": _FETCH_USER_AGENT},
            stream=True,
        )
        try:
            # requests follows redirects — a public URL may 302 to an
            # internal address, so the final URL must pass the guard too.
            try:
                _validate_public_http_url(str(response.url))
            except ValueError as exc:
                return _error(str(exc))
            response.raise_for_status()

            chunks: list[bytes] = []
            received = 0
            truncated_bytes = False
            for chunk in response.iter_content(chunk_size=65536):
                received += len(chunk)
                if received > _FETCH_MAX_BYTES:
                    truncated_bytes = True
                    chunks.append(chunk[: _FETCH_MAX_BYTES - (received - len(chunk))])
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)

            content_type = (
                response.headers.get("content-type", "text/html").split(";")[0].strip().lower()
            )
            encoding = response.encoding or "utf-8"
            final_url = str(response.url)
            status_code = response.status_code
        finally:
            response.close()
    except Exception as exc:
        return _error(f"Fetch failed: {exc}")

    title = ""
    if content_type in {"text/html", "application/xhtml+xml"}:
        raw_html = raw.decode(encoding, errors="replace")
        text = _clean_html_text(raw_html)
        title = _extract_html_title(raw_html) or ""
    elif content_type.startswith("text/") or content_type in _FETCH_RAW_TEXT_TYPES:
        text = raw.decode(encoding, errors="replace")
    else:
        return _error(
            f"Unsupported content type {content_type!r}. "
            "Add this URL as a chat source instead to have it converted."
        )

    truncated = truncated_bytes or len(text) > max_chars
    text = text[:max_chars]
    return {
        "url": str(url),
        "final_url": final_url,
        "title": title,
        "content_type": content_type,
        "status_code": status_code,
        "text": text,
        "text_chars": len(text),
        "truncated": truncated,
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
                "Include dates or version numbers for best results. "
                'E.g. "Python 3.13 new features" or '
                '"global inflation rate Q1 2026"'
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

FETCH_URL_SCHEMA = _schema(
    "fetch_url",
    "Fetch a specific web page URL and return its readable text content. "
    "Use when the user shares a URL and asks to read, open, extract, or "
    "summarize that exact page. For open-ended questions use web_search "
    "instead; for PDFs or other binary documents suggest adding the URL "
    "as a chat source so it can be converted.",
    {
        "url": {
            "type": "string",
            "description": "The http(s) URL to fetch. Private/local addresses are refused.",
        },
        "max_chars": {
            "type": "integer",
            "description": "Max characters of extracted text to return (default 20000).",
        },
    },
    ["url"],
)

WEB_SEARCH_MULTI_SCHEMA = _schema(
    "web_search_multi",
    "Search the web for multiple queries in one call. Each query runs "
    "independently. Use when you need to gather information from several "
    "angles before synthesizing (e.g. search for a topic AND its "
    "latest updates AND related statistics).",
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
