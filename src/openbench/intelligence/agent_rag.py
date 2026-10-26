"""RAG retrieval mixin for BaseAgent.

Holds the knowledge-base retrieval, query-rewriting, and context-augmentation
methods so ``base.py`` keeps the reasoning loop. Mixed into ``BaseAgent``; it
relies on the host providing ``store``, ``model``, ``retrieval_top_k``,
``retrieval_threshold``, the query-rewriter state, and ``_get_llm()``.
"""

from __future__ import annotations

import logging
from typing import Any

from openbench.core.abstractions import ExecutionContext, Query
from openbench.intelligence.query_rewriter import QueryRewriter

logger = logging.getLogger(__name__)


class _AgentRAGMixin:
    """RAG retrieval helpers for BaseAgent; not instantiated directly."""

    def _get_query_rewriter(self) -> QueryRewriter | None:
        """Get query rewriter, lazily initialized."""
        if not self._query_rewriter_enabled:
            return None
        if self._query_rewriter is None:
            self._query_rewriter = QueryRewriter(self._get_llm(), self.model)
        return self._query_rewriter

    def _rag_tool_retrieve(self, query: str) -> str:
        """Tool function for multi-hop RAG retrieval.

        Called by the agent's reasoning loop via the ``retrieve_knowledge`` tool.

        Args:
            query: Search query for the knowledge base.

        Returns:
            Formatted string with retrieved chunks, or a "not found" message.
        """
        if not self.store:
            return "No knowledge base configured."

        results = self._retrieve_context(query)
        if not results:
            return "No relevant documents found for this query."

        parts = []
        for i, item in enumerate(results, 1):
            parts.append(f"[Source {i}] (relevance: {item['score']:.2f})\n{item['content']}")
        return "\n\n---\n\n".join(parts)

    def _retrieve_context(self, query_text: str) -> list[dict[str, Any]]:
        """Retrieve relevant context from store for RAG.

        Supports query rewriting: when enabled, the query is rewritten into
        1-3 optimized queries and results are deduplicated.

        Args:
            query_text: Text to search for relevant context.

        Returns:
            List of retrieved items with content and metadata.
        """
        if not self.store:
            return []

        try:
            rewriter = self._get_query_rewriter()
            queries = rewriter.rewrite(query_text) if rewriter else [query_text]

            # Retrieve for each query, deduplicate by content hash
            all_retrieved: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            for q in queries:
                results = self.store.search(Query(text=q, limit=self.retrieval_top_k))

                for item, score in zip(results.items, results.scores, strict=True):
                    if score < self.retrieval_threshold:
                        continue
                    item_id = item.get("id", item.get("content", "")[:100])
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    all_retrieved.append(
                        {
                            "content": item.get("content", ""),
                            "score": score,
                            "metadata": item.get("metadata", {}),
                        }
                    )

            # Sort by score descending, cap at top_k
            all_retrieved.sort(key=lambda x: x["score"], reverse=True)
            return all_retrieved[: self.retrieval_top_k]

        except Exception as e:
            logger.warning(f"Failed to retrieve context from store: {e}")
            return []

    def _augment_context_with_rag(
        self, context: ExecutionContext, retrieved: list[dict[str, Any]]
    ) -> ExecutionContext:
        """Augment execution context with retrieved RAG context.

        Args:
            context: Original execution context.
            retrieved: Retrieved items from store.

        Returns:
            Augmented execution context.
        """
        if not retrieved:
            return context

        # Build RAG context string
        rag_context_parts = []
        for i, item in enumerate(retrieved, 1):
            rag_context_parts.append(
                f"[Source {i}] (relevance: {item['score']:.2f})\n{item['content']}"
            )

        rag_context = "\n\n---\n\n".join(rag_context_parts)

        # Augment context data
        augmented_data = context.data or {}
        if isinstance(augmented_data, dict):
            augmented_data = {
                **augmented_data,
                "_rag_context": rag_context,
                "_rag_sources": len(retrieved),
            }
        else:
            augmented_data = {
                "original_data": augmented_data,
                "_rag_context": rag_context,
                "_rag_sources": len(retrieved),
            }

        return ExecutionContext(
            goal=context.goal,
            data=augmented_data,
            tools=context.tools,
            memory=context.memory,
            constraints=context.constraints,
        )
