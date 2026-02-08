"""Grounded search data source - LLM with built-in web search.

Returns synthesized answers with citations from LLMs that have
built-in web search/grounding capabilities.

For raw search results, use WebSearchDataSource instead.

Supported providers:
- gemini: Google Gemini with Google Search grounding
- perplexity: Perplexity API (AI-powered search with citations)

Example:
    # Gemini with grounding
    source = GroundedSearchSource(
        query="What are the latest AI trends in 2026?",
        provider="gemini"
    )
    result = source.extract()
    print(result.content)  # Synthesized answer with citations

    # Perplexity
    source = GroundedSearchSource(
        query="Explain quantum computing",
        provider="perplexity"
    )
"""

import hashlib
import logging
import os
import urllib.request
from datetime import datetime
from typing import Any, Literal

from openbench.core.abstractions import DataSource, RawData
from openbench.data.exceptions import ExtractionError, ValidationError

logger = logging.getLogger(__name__)

GroundedProvider = Literal["gemini", "perplexity"]

GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"


def _resolve_redirect_url(url: str, timeout: float = 5.0) -> str:
    """Resolve a Vertex AI grounding redirect URL to its actual destination.

    Args:
        url: URL that may be a grounding redirect.
        timeout: HTTP request timeout in seconds.

    Returns:
        Resolved URL, or original URL if resolution fails.
    """
    if GROUNDING_REDIRECT_HOST not in url:
        return url

    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.url
    except Exception as e:
        logger.debug(f"Failed to resolve grounding redirect: {e}")
        return url


class GroundedSearchSource(DataSource):
    """LLM-grounded search data source.

    Uses LLMs with built-in web search capabilities to return
    synthesized answers with citations.

    Unlike WebSearchDataSource (raw results), this returns
    AI-generated answers grounded in web search.

    Providers:
        - gemini: Google Gemini with Google Search grounding
        - perplexity: Perplexity API with real-time web search

    Example:
        # Direct answer with citations
        source = GroundedSearchSource(
            query="What is the current state of AI?",
            provider="gemini"
        )
        result = source.extract()
        print(result.content)  # Synthesized answer
        print(result.metadata["sources"])  # Citation URLs

        # In workflow (no need for additional Agent)
        workflow = (
            GroundedSearchSource(query="latest news")
            | OutputGenerator()
        )
    """

    ENV_KEYS = {
        "gemini": ["GOOGLE_API_KEY"],
        "perplexity": ["PERPLEXITY_API_KEY"],
    }

    DEFAULT_MODELS = {
        "gemini": "gemini-2.5-flash",
        "perplexity": "llama-3.1-sonar-small-128k-online",
    }

    def __init__(
        self,
        query: str,
        provider: GroundedProvider = "gemini",
        model: str | None = None,
        api_key: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """Initialize grounded search source.

        Args:
            query: Search/question to answer.
            provider: LLM provider with grounding (default: "gemini").
            model: Model to use (uses provider default if not specified).
            api_key: API key (reads from env if not provided).
            system_prompt: Custom system prompt for the LLM.
            temperature: Generation temperature (default: 0.7).
            max_tokens: Maximum output tokens (default: 4096).
        """
        self.query = query
        self.provider = provider
        self.model = model or self.DEFAULT_MODELS.get(provider)
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.api_key = api_key or self._get_api_key()
        self._sources: list[dict[str, Any]] = []

    def _default_system_prompt(self) -> str:
        return """You are a research assistant with real-time web search capabilities.

When answering questions:
1. Search for relevant, up-to-date information
2. Synthesize findings into a comprehensive answer
3. Cite sources clearly
4. Be factual and objective
5. Acknowledge when information is uncertain or unavailable"""

    def _get_api_key(self) -> str | None:
        """Get API key from environment."""
        for key_name in self.ENV_KEYS.get(self.provider, []):
            if key := os.getenv(key_name):
                return key
        return None

    @property
    def source_type(self) -> str:
        return "grounded_search"

    @property
    def source_id(self) -> str:
        query_hash = hashlib.md5(self.query.encode()).hexdigest()[:8]
        return f"grounded_{self.provider}_{query_hash}"

    def validate(self) -> bool:
        if not self.query or not self.query.strip():
            raise ValidationError("Query cannot be empty")

        if self.provider not in self.ENV_KEYS:
            raise ValidationError(
                f"Unsupported provider: {self.provider}. Available: {list(self.ENV_KEYS.keys())}"
            )

        if not self.api_key:
            env_vars = self.ENV_KEYS.get(self.provider, [])
            raise ValidationError(
                f"API key required for {self.provider}. "
                f"Set via api_key or env: {', '.join(env_vars)}"
            )

        return True

    def get_metadata(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def _search_gemini(self) -> dict[str, Any]:
        """Search using Gemini with Google Search grounding."""
        # Try new SDK first (google-genai), fall back to old (google-generativeai)
        try:
            return self._search_gemini_new_sdk()
        except ImportError:
            return self._search_gemini_old_sdk()

    def _search_gemini_new_sdk(self) -> dict[str, Any]:
        """Use new google-genai SDK."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        grounding_tool = types.Tool(google_search=types.GoogleSearch())

        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            tools=[grounding_tool],
        )

        response = client.models.generate_content(
            model=self.model,
            contents=self.query,
            config=config,
        )

        # Extract sources from grounding metadata
        sources = []
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "grounding_metadata"):
                grounding = candidate.grounding_metadata
                if (
                    grounding
                    and hasattr(grounding, "grounding_chunks")
                    and grounding.grounding_chunks
                ):
                    for chunk in grounding.grounding_chunks:
                        if hasattr(chunk, "web"):
                            raw_url = getattr(chunk.web, "uri", "")
                            sources.append(
                                {
                                    "title": getattr(chunk.web, "title", ""),
                                    "url": _resolve_redirect_url(raw_url),
                                }
                            )
                if (
                    grounding
                    and hasattr(grounding, "search_entry_point")
                    and hasattr(grounding.search_entry_point, "rendered_content")
                ):
                    sources.append(
                        {
                            "type": "search_suggestion",
                            "content": grounding.search_entry_point.rendered_content,
                        }
                    )

        return {
            "content": response.text,
            "sources": sources,
            "model": self.model,
        }

    def _search_gemini_old_sdk(self) -> dict[str, Any]:
        """Use old google-generativeai SDK (without grounding)."""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ExtractionError(
                "google-genai or google-generativeai required. Install: pip install google-genai"
            ) from None

        genai.configure(api_key=self.api_key)

        # Old SDK doesn't support google_search tool easily
        # Use standard generation with search-focused prompt
        model = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=self.system_prompt,
            generation_config={
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            },
        )

        # Enhanced prompt for search-like behavior
        search_prompt = f"""Search the web and provide current information about: {self.query}

Provide factual, up-to-date information with sources where possible."""

        response = model.generate_content(search_prompt)

        return {
            "content": response.text,
            "sources": [],
            "model": self.model,
        }

    def _search_perplexity(self) -> dict[str, Any]:
        """Search using Perplexity API."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ExtractionError(
                "openai required for Perplexity. Install: pip install openai"
            ) from None

        client = OpenAI(api_key=self.api_key, base_url="https://api.perplexity.ai")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.query},
        ]

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        content = response.choices[0].message.content

        # Extract citations if available
        sources = []
        if hasattr(response, "citations"):
            for i, url in enumerate(response.citations):
                sources.append(
                    {
                        "title": f"Source {i + 1}",
                        "url": url,
                    }
                )

        return {
            "content": content,
            "sources": sources,
            "model": self.model,
        }

    def extract(self) -> RawData:
        """Execute grounded search and return synthesized answer.

        Returns:
            RawData with AI-generated answer and source citations.
        """
        self.validate()

        search_methods = {
            "gemini": self._search_gemini,
            "perplexity": self._search_perplexity,
        }

        try:
            result = search_methods[self.provider]()
        except Exception as e:
            raise ExtractionError(f"{self.provider} grounded search failed: {e}") from e

        self._sources = result.get("sources", [])

        # Format content with sources
        content_parts = [
            f"# Grounded Search: {self.query}",
            f"Provider: {self.provider} ({result.get('model', 'N/A')})",
            "",
            "## Answer",
            result["content"],
        ]

        if self._sources:
            content_parts.append("\n## Sources")
            for i, src in enumerate(self._sources, 1):
                if src.get("type") == "search_query":
                    content_parts.append(f"- Search: {src.get('query', '')}")
                else:
                    title = src.get("title", f"Source {i}")
                    url = src.get("url", "")
                    content_parts.append(f"[{i}] {title}: {url}")

        content = "\n".join(content_parts)

        metadata = {
            **self.get_metadata(),
            "searched_at": datetime.now().isoformat(),
            "sources": self._sources,
            "source_count": len(self._sources),
            "answer_length": len(result["content"]),
        }

        return RawData(
            content=content,
            content_type="text",
            metadata=metadata,
            source=self,
        )

    def invoke(self, input: Any = None, config: Any | None = None) -> RawData:
        """Chainable invoke for workflow composition."""
        if isinstance(input, dict) and "query" in input:
            self.query = input["query"]
        elif isinstance(input, str):
            self.query = input
        return self.extract()

    async def aextract(self) -> RawData:
        """Async extraction."""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(None, self.extract)

    def get_sources(self) -> list[dict[str, Any]]:
        """Get extracted sources after calling extract().

        Returns:
            List of source dictionaries with title and url.
        """
        return self._sources
