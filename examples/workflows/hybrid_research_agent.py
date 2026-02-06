"""
Hybrid Research Agent - RAG + Web Search

Demonstrates hybrid architecture combining:
    1. PineconeStore (RAG) - Known/indexed knowledge
    2. WebSearchDataSource - Raw web search results
    3. GroundedSearchSource - LLM-grounded search (Gemini/Perplexity)

Usage:
    # Grounded search (Gemini with built-in web)
    python hybrid_research_agent.py "What are AI trends in 2026?" --mode grounded

    # RAG with auto-detected namespace (detects "japfa" in query)
    python hybrid_research_agent.py "check japfa company profile" --mode rag

    # RAG with explicit namespace
    python hybrid_research_agent.py "company overview" --mode rag --namespace japfa

    # List available namespaces
    python hybrid_research_agent.py --list-namespaces

    # Full hybrid (RAG + Grounded)
    python hybrid_research_agent.py "sustainability trends" --mode hybrid --namespace japfa

Requires:
    - GOOGLE_API_KEY
    - PINECONE_API_KEY (for RAG mode)
"""

import argparse
import os
import re
import sys
from typing import Dict, List, Optional

from openbench.core.abstractions import Query
from openbench.data.sources import WebSearchDataSource, GroundedSearchSource
from openbench.adapters import GoogleADKAdapter


# Known namespaces with keywords for auto-detection
KNOWN_NAMESPACES: Dict[str, List[str]] = {
    "japfa": ["japfa", "pt japfa", "japfa tbk", "japfa comfeed"],
    "knowledge-base": ["default", "general"],
}


def detect_namespace(query: str, default: str = "knowledge-base") -> str:
    """Auto-detect namespace from query keywords.

    Args:
        query: User query string.
        default: Default namespace if no match.

    Returns:
        Detected namespace name.
    """
    query_lower = query.lower()

    for namespace, keywords in KNOWN_NAMESPACES.items():
        for keyword in keywords:
            if keyword in query_lower:
                return namespace

    return default


def list_namespaces(index_name: str = "openbench") -> Dict[str, int]:
    """List available namespaces in Pinecone index.

    Returns:
        Dict of namespace -> vector count.
    """
    try:
        from openbench.data.stores import PineconeStore
        from openbench.intelligence import GoogleEmbeddingProvider

        embedding_provider = GoogleEmbeddingProvider(model="text-embedding-004")
        store = PineconeStore(
            index_name=index_name,
            namespace="",  # Empty to get index stats
            embedding_provider=embedding_provider,
            create_if_missing=False,
        )

        stats = store.describe_index()
        namespaces = {}

        if stats.get("namespaces"):
            for ns, data in stats["namespaces"].items():
                namespaces[ns] = data.get("vector_count", 0)

        return namespaces

    except Exception as e:
        print(f"Error listing namespaces: {e}")
        return {}


class HybridResearchAgent:
    """Research agent with multiple search strategies.

    Modes:
        - grounded: Use GroundedSearchSource (Gemini/Perplexity with built-in web)
        - raw: Use WebSearchDataSource + Agent for synthesis
        - rag: Use PineconeStore only
        - hybrid: Combine RAG + Grounded search

    Example:
        agent = HybridResearchAgent(mode="grounded")
        result = agent.research("What are AI trends?")
        print(result["answer"])
    """

    def __init__(
        self,
        mode: str = "grounded",
        # RAG settings
        index_name: str = "openbench",
        namespace: Optional[str] = None,  # None = auto-detect
        auto_detect_namespace: bool = True,
        # Search settings
        grounded_provider: str = "gemini",
        raw_provider: str = "duckduckgo",
        # LLM settings
        model: str = "gemini-2.5-flash",
        top_k: int = 5,
        max_results: int = 5,
        quiet: bool = False,
    ):
        """Initialize agent.

        Args:
            mode: Search mode (grounded, raw, rag, hybrid).
            index_name: Pinecone index for RAG.
            namespace: Pinecone namespace. If None, auto-detect from query.
            auto_detect_namespace: Enable namespace auto-detection from query.
            grounded_provider: Provider for grounded search (gemini, perplexity).
            raw_provider: Provider for raw search (tavily, serpapi, duckduckgo).
            model: LLM model.
            top_k: RAG results count.
            max_results: Web results count.
            quiet: Suppress debug output for chatbot integration.
        """
        self.mode = mode
        self.index_name = index_name
        self.namespace = namespace or "knowledge-base"
        self.auto_detect_namespace = auto_detect_namespace
        self.grounded_provider = grounded_provider
        self.raw_provider = raw_provider
        self.model = model
        self.top_k = top_k
        self.max_results = max_results
        self.quiet = quiet

        self._init_components()
        self.history: List[dict] = []

    def _log(self, message: str):
        """Print message if not in quiet mode."""
        if not self.quiet:
            print(message)

    def _init_components(self):
        """Initialize components based on mode."""
        # RAG Store
        self.store = None
        if self.mode in ("rag", "hybrid"):
            try:
                from openbench.data.stores import PineconeStore
                from openbench.intelligence import GoogleEmbeddingProvider

                self._log(f"\n🔧 Initializing RAG components...")
                self._log(f"   Index: {self.index_name}")
                self._log(f"   Namespace: {self.namespace}")

                self.embedding_provider = GoogleEmbeddingProvider(model="text-embedding-004")
                self.store = PineconeStore(
                    index_name=self.index_name,
                    namespace=self.namespace,
                    embedding_provider=self.embedding_provider,
                    create_if_missing=False,
                )

                # Verify namespace exists
                stats = self.store.describe_index()
                namespaces = stats.get("namespaces", {})
                if self.namespace in namespaces:
                    count = namespaces[self.namespace].get("vector_count", 0)
                    self._log(f"   ✓ Namespace '{self.namespace}' found: {count} vectors")
                else:
                    self._log(f"   ⚠ Namespace '{self.namespace}' not found!")
                    self._log(f"   Available: {list(namespaces.keys())}")

            except Exception as e:
                self._log(f"   ✗ RAG disabled - {e}")
                if not self.quiet:
                    import traceback
                    traceback.print_exc()

        # LLM for raw search synthesis
        if self.mode == "raw":
            self.llm = GoogleADKAdapter(
                model=self.model,
                system_instruction="""You are a research assistant.
Synthesize the web search results into a comprehensive answer.
Cite sources using [1], [2], etc.""",
            )

    def search_rag(self, query: str) -> List[dict]:
        """Search vector store."""
        self._log(f"\n📚 RAG Search")
        self._log(f"   Query: '{query}'")
        self._log(f"   Store: {self.store is not None}")

        if not self.store:
            self._log("   ✗ Store not initialized - check error above")
            return []

        try:
            self._log(f"   Searching namespace '{self.namespace}' (top_k={self.top_k})...")
            result = self.store.search(Query(text=query, limit=self.top_k))
            self._log(f"   ✓ Found {len(result.items)} results")

            if not result.items:
                self._log("   ⚠ No results returned from Pinecone")
                self._log("   Check: Is the namespace correct? Are documents indexed?")
                return []

            docs = []
            self._log(f"\n   Results (threshold: 0.7):")
            for i, item in enumerate(result.items):
                score = result.scores[i] if result.scores else 0
                content_preview = item.get("content", "")[:80].replace("\n", " ")
                status = "✓" if score >= 0.7 else "✗"
                self._log(f"   {status} [{i+1}] score={score:.3f} | {content_preview}...")
                if score >= 0.7:
                    docs.append({
                        "id": f"RAG-{i+1}",
                        "content": item.get("content", "")[:2000],
                        "score": score,
                        "source": item.get("metadata", {}).get("filename", "Internal"),
                    })

            self._log(f"\n   Summary: {len(docs)}/{len(result.items)} passed threshold")
            return docs
        except Exception as e:
            self._log(f"   ✗ RAG search error: {e}")
            if not self.quiet:
                import traceback
                traceback.print_exc()
            return []

    def search_grounded(self, query: str) -> dict:
        """Use GroundedSearchSource (LLM with built-in web)."""
        source = GroundedSearchSource(
            query=query,
            provider=self.grounded_provider,
            model=self.model,
        )
        result = source.extract()

        return {
            "answer": result.content,
            "sources": result.metadata.get("sources", []),
            "type": "grounded",
        }

    def search_raw(self, query: str) -> dict:
        """Use WebSearchDataSource + Agent synthesis."""
        # Get raw results
        source = WebSearchDataSource(
            query=query,
            provider=self.raw_provider,
            max_results=self.max_results,
        )
        raw_result = source.extract()

        # Synthesize with LLM
        prompt = f"""Based on these web search results, answer: {query}

{raw_result.content}

Provide a comprehensive answer with citations."""

        llm_result = self.llm.invoke({"goal": prompt})

        return {
            "answer": llm_result.get("content", ""),
            "sources": raw_result.metadata.get("results", []),
            "type": "raw",
        }

    def research(self, query: str) -> dict:
        """Perform research based on mode."""
        # Auto-detect namespace from query if enabled
        if self.auto_detect_namespace and self.mode in ("rag", "hybrid"):
            detected_ns = detect_namespace(query, self.namespace)
            if detected_ns != self.namespace:
                self._log(f"\n🎯 Auto-detected namespace: {detected_ns}")
                self.namespace = detected_ns
                self._init_components()  # Reinitialize with new namespace

        self._log(f"\n🔍 Mode: {self.mode}")
        if self.mode in ("rag", "hybrid"):
            self._log(f"   Namespace: {self.namespace}")
        self._log(f"   Query: {query}")

        results = {"query": query, "mode": self.mode}

        if self.mode == "grounded":
            self._log(f"   Using GroundedSearchSource ({self.grounded_provider})...")
            res = self.search_grounded(query)
            results["answer"] = res["answer"]
            results["sources"] = res["sources"]

        elif self.mode == "raw":
            self._log(f"   Using WebSearchDataSource ({self.raw_provider}) + Agent...")
            res = self.search_raw(query)
            results["answer"] = res["answer"]
            results["sources"] = res["sources"]

        elif self.mode == "rag":
            self._log("   Using RAG only...")
            rag_docs = self.search_rag(query)
            if rag_docs:
                context = "\n\n".join([f"[{d['id']}] {d['content']}" for d in rag_docs])
                llm = GoogleADKAdapter(model=self.model)
                res = llm.invoke({"goal": f"Answer based on context:\n{context}\n\nQuestion: {query}"})
                results["answer"] = res.get("content", "")
                results["sources"] = [{"id": d["id"], "source": d["source"]} for d in rag_docs]
            else:
                results["answer"] = "No relevant documents found in knowledge base."
                results["sources"] = []

        elif self.mode == "hybrid":
            self._log("   Using Hybrid (RAG + Web Enrichment)...")

            # Get RAG results first
            rag_docs = self.search_rag(query)

            if rag_docs:
                # Build context from RAG
                rag_context = "\n\n".join(
                    [f"[{i+1}] Source: {d['source']}\n{d['content']}" for i, d in enumerate(rag_docs)]
                )

                # Use LLM to synthesize RAG results
                enrichment_prompt = f"""You are a research assistant analyzing internal company documents.

INTERNAL DOCUMENTS (from knowledge base):
{rag_context}

USER QUESTION: {query}

Instructions:
1. Extract and present ALL relevant financial data, numbers, and facts from the documents above
2. If the documents contain tables or numerical data, present them clearly
3. Cite sources as [1], [2], etc. matching the document numbers above
4. If specific data is not found, state what related information IS available
5. Be comprehensive - include all relevant numbers and details from the documents

IMPORTANT: Focus on extracting actual data from the documents, not summarizing what's missing."""

                self._log("   Enriching RAG results with LLM...")
                llm = GoogleADKAdapter(model=self.model)
                res = llm.invoke({"goal": enrichment_prompt})

                results["answer"] = res.get("content", "")
                results["sources"] = {
                    "rag": [{"id": d["id"], "source": d["source"], "score": d["score"]} for d in rag_docs],
                }
            else:
                # No RAG results, fall back to grounded search only
                self._log("   No RAG results, using grounded search...")
                try:
                    grounded = self.search_grounded(query)
                    results["answer"] = grounded["answer"]
                    results["sources"] = {"web": grounded["sources"]}
                except Exception as e:
                    self._log(f"   ⚠ Grounded search failed: {e}")
                    # Final fallback to plain LLM
                    llm = GoogleADKAdapter(model=self.model)
                    res = llm.invoke({"goal": f"Answer this question: {query}"})
                    results["answer"] = res.get("content", "")
                    results["sources"] = {}

        self.history.append(results)
        return results


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid Research Agent - RAG + Web Search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Known Namespaces (auto-detected from query):
  japfa          - PT Japfa Tbk documents (keywords: japfa, pt japfa)
  knowledge-base - Default namespace

Examples:
  # Auto-detect namespace from query
  python hybrid_research_agent.py "check japfa company profile" --mode rag

  # Explicit namespace
  python hybrid_research_agent.py "revenue 2024" --mode rag --namespace japfa

  # List available namespaces
  python hybrid_research_agent.py --list-namespaces
        """
    )
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("--mode", default="grounded",
                        choices=["grounded", "raw", "rag", "hybrid"],
                        help="Search mode (default: grounded)")
    parser.add_argument("--grounded-provider", default="gemini",
                        choices=["gemini", "perplexity"])
    parser.add_argument("--raw-provider", default="duckduckgo",
                        choices=["tavily", "serpapi", "duckduckgo"])
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--index", default="openbench", help="Pinecone index name")
    parser.add_argument("--namespace", default=None,
                        help="Pinecone namespace (auto-detected if not specified)")
    parser.add_argument("--no-auto-detect", action="store_true",
                        help="Disable namespace auto-detection")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Quiet mode - minimal output for chatbot integration")
    parser.add_argument("--list-namespaces", "-l", action="store_true",
                        help="List available namespaces in Pinecone")
    parser.add_argument("--interactive", "-i", action="store_true")
    args = parser.parse_args()

    # List namespaces
    if args.list_namespaces:
        if not os.getenv("PINECONE_API_KEY"):
            print("Error: PINECONE_API_KEY required for --list-namespaces")
            sys.exit(1)
        if not os.getenv("GOOGLE_API_KEY"):
            print("Error: GOOGLE_API_KEY required for embeddings")
            sys.exit(1)

        print(f"\n📚 Namespaces in index '{args.index}':")
        print("-" * 40)
        namespaces = list_namespaces(args.index)
        if namespaces:
            for ns, count in sorted(namespaces.items()):
                keywords = KNOWN_NAMESPACES.get(ns, [])
                kw_str = f" (keywords: {', '.join(keywords)})" if keywords else ""
                print(f"  {ns}: {count} vectors{kw_str}")
        else:
            print("  No namespaces found or error occurred.")
        print()
        return

    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY required")
        sys.exit(1)

    agent = HybridResearchAgent(
        mode=args.mode,
        index_name=args.index,
        namespace=args.namespace,
        auto_detect_namespace=not args.no_auto_detect,
        grounded_provider=args.grounded_provider,
        raw_provider=args.raw_provider,
        model=args.model,
        quiet=args.quiet,
    )

    if args.interactive:
        print("\n" + "=" * 60)
        print("Hybrid Research Agent - Interactive")
        print("=" * 60)
        print(f"Mode: {args.mode} | Namespace: {agent.namespace}")
        print("Commands:")
        print("  /grounded, /raw, /rag, /hybrid - Switch mode")
        print("  /ns <name> - Switch namespace (e.g., /ns japfa)")
        print("  /list - List namespaces")
        print("  /quit - Exit")
        print("-" * 60)

        while True:
            try:
                query = input("\n📝 You: ").strip()
                if not query:
                    continue
                if query == "/quit":
                    break
                if query == "/list":
                    namespaces = list_namespaces(args.index)
                    print("\n📚 Available namespaces:")
                    for ns, count in sorted(namespaces.items()):
                        marker = "→" if ns == agent.namespace else " "
                        print(f"  {marker} {ns}: {count} vectors")
                    continue
                if query.startswith("/ns "):
                    new_ns = query[4:].strip()
                    agent.namespace = new_ns
                    agent._init_components()
                    print(f"Namespace: {new_ns}")
                    continue
                if query.startswith("/"):
                    mode = query[1:]
                    if mode in ("grounded", "raw", "rag", "hybrid"):
                        agent.mode = mode
                        agent._init_components()
                        print(f"Mode: {mode}")
                    continue

                result = agent.research(query)
                print(f"\n🤖 Answer:\n{result['answer']}")

                # Show sources in interactive mode
                if result.get("sources"):
                    sources = result["sources"]
                    if isinstance(sources, dict) and sources.get("rag"):
                        print("\n📚 Sources:")
                        for src in sources["rag"]:
                            print(f"   [{src['id']}] {src['source']} ({src.get('score', 0):.2f})")

            except KeyboardInterrupt:
                break

    elif args.query:
        result = agent.research(args.query)

        # Build complete response with sources embedded
        output_parts = []

        # Add instruction for agent to pass through
        output_parts.append("=== RESEARCH RESULT (COPY THIS VERBATIM TO USER) ===\n")
        output_parts.append(result["answer"])

        # Add sources directly after answer
        if result.get("sources"):
            sources = result["sources"]
            source_lines = ["\n\n---\n**Sources:**"]

            if isinstance(sources, dict) and sources.get("rag"):
                for src in sources["rag"]:
                    score = src.get("score", 0)
                    source_lines.append(f"- [{src['id']}] {src['source']} (relevance: {score:.0%})")
            elif isinstance(sources, list):
                for src in sources:
                    if isinstance(src, dict):
                        src_id = src.get("id", "")
                        src_name = src.get("source", src.get("title", "Unknown"))
                        source_lines.append(f"- {src_id} {src_name}")

            output_parts.append("\n".join(source_lines))

        output_parts.append("\n\n=== END RESULT (SHOW ALL ABOVE TO USER) ===")

        # Print complete response
        print("\n".join(output_parts))

    else:
        parser.print_help()
        print("\nExamples:")
        print('  python hybrid_research_agent.py "AI trends 2026" --mode grounded')
        print('  python hybrid_research_agent.py "latest news" --mode raw --raw-provider duckduckgo')
        print('  python hybrid_research_agent.py --interactive')


if __name__ == "__main__":
    main()
