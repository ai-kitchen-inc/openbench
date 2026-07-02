"""LLM-based query rewriting for improved RAG retrieval.

Provides :class:`QueryRewriter`, which expands a user query into 1-3 optimized
search queries. Extracted from ``intelligence/base.py``; ``base`` still
re-exports it for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbench.core.abstractions import LLMProvider

logger = logging.getLogger(__name__)


class QueryRewriter:
    """LLM-based query rewriter for improved RAG retrieval.

    Rewrites user queries into multiple optimized search queries
    to improve semantic search recall.

    Example:
        >>> rewriter = QueryRewriter(llm_provider)
        >>> queries = rewriter.rewrite("How does photosynthesis affect climate?")
        >>> # ["photosynthesis carbon dioxide absorption", "climate change CO2 cycle", ...]
    """

    def __init__(self, llm: LLMProvider, model: str | None = None):
        self.llm = llm
        self.model = model

    def rewrite(self, query: str, context: str = "") -> list[str]:
        """Rewrite a query into 1-3 optimized search queries.

        Args:
            query: Original user query.
            context: Optional additional context to inform rewriting.

        Returns:
            List of rewritten search queries (1-3 items).
            Falls back to [query] on failure.
        """
        prompt = (
            "Given the user query below, generate 1 to 3 search queries optimized for "
            "semantic search over a document knowledge base. Each query should target "
            "a different aspect of the information need.\n\n"
            f"User query: {query}\n"
        )
        if context:
            prompt += f"Additional context: {context}\n"
        prompt += '\nRespond with ONLY a JSON array of strings, e.g. ["query1", "query2"].'

        try:
            response = self.llm.generate(prompt=prompt, model=self.model, temperature=0.3)
            text = response.text.strip()
            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            queries = json.loads(text)
            if isinstance(queries, list) and queries and all(isinstance(q, str) for q in queries):
                return queries[:3]  # Cap at 3
        except Exception as e:
            logger.warning(f"Query rewriting failed, using original query: {e}")

        return [query]
