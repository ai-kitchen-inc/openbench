"""
Research Agent - Agentic RAG from Pinecone Knowledge Base

Demonstrates agentic research workflow:
    Query -> PineconeStore (RAG) -> GoogleADK Agent -> Response

The agent can:
    1. Search the knowledge base for relevant information
    2. Synthesize findings into coherent responses
    3. Cite sources with references
    4. Handle follow-up questions

Usage:
    python examples/workflows/research/research_agent.py "What is sustainability?"
    python examples/workflows/research/research_agent.py "Explain the key findings" --namespace my-project
    python examples/workflows/research/research_agent.py --interactive

Requires:
    - PINECONE_API_KEY environment variable
    - GOOGLE_API_KEY environment variable
    - Pre-indexed documents (use pdf_indexer.py first)
"""

import argparse
import os
import sys
from typing import List, Optional

from openbench.core.abstractions import Query
from openbench.data.stores import PineconeStore
from openbench.intelligence import GoogleEmbeddingProvider
from openbench.adapters import GoogleADKAdapter


class ResearchAgent:
    """Agentic research assistant using RAG from Pinecone.

    This agent:
    1. Retrieves relevant context from vector store
    2. Synthesizes information using LLM
    3. Provides cited responses

    Example:
        ```python
        agent = ResearchAgent(namespace="my-docs")
        response = agent.research("What are the main findings?")
        print(response["answer"])
        print(response["sources"])
        ```
    """

    def __init__(
        self,
        index_name: str = "openbench",
        namespace: str = "knowledge-base",
        model: str = "gemini-2.5-flash",
        top_k: int = 5,
        min_score: float = 0.7,
    ):
        """Initialize Research Agent.

        Args:
            index_name: Pinecone index name
            namespace: Pinecone namespace
            model: LLM model for synthesis
            top_k: Number of results to retrieve
            min_score: Minimum similarity score
        """
        self.index_name = index_name
        self.namespace = namespace
        self.model = model
        self.top_k = top_k
        self.min_score = min_score

        # Initialize components
        self._init_components()

        # Conversation history for context
        self.history: List[dict] = []

    def _init_components(self):
        """Initialize store and LLM."""
        # Embedding provider
        self.embedding_provider = GoogleEmbeddingProvider(model="text-embedding-004")

        # Vector store
        self.store = PineconeStore(
            index_name=self.index_name,
            namespace=self.namespace,
            embedding_provider=self.embedding_provider,
            create_if_missing=False,
        )

        # LLM for synthesis
        self.llm = GoogleADKAdapter(
            model=self.model,
            system_instruction="""You are a research assistant with access to a knowledge base.

Your task:
1. Analyze the provided context from the knowledge base
2. Synthesize information to answer the user's question
3. Always cite sources using [1], [2], etc.
4. If the context doesn't contain relevant information, say so clearly
5. Be concise but comprehensive

Format your response as:
- Direct answer to the question
- Supporting details with citations
- Any caveats or limitations""",
        )

    def search(self, query: str) -> List[dict]:
        """Search knowledge base for relevant content.

        Args:
            query: Search query

        Returns:
            List of relevant documents with scores
        """
        search_query = Query(
            text=query,
            limit=self.top_k,
        )

        result = self.store.search(search_query)

        # Filter by minimum score
        relevant = []
        for i, item in enumerate(result.items):
            score = result.scores[i] if result.scores else 0
            if score >= self.min_score:
                relevant.append({
                    "id": item.get("id", f"doc-{i}"),
                    "content": item.get("content", ""),
                    "score": score,
                    "metadata": item.get("metadata", {}),
                })

        return relevant

    def synthesize(self, query: str, context: List[dict]) -> str:
        """Synthesize answer from context using LLM.

        Args:
            query: User question
            context: Retrieved documents

        Returns:
            Synthesized answer
        """
        if not context:
            return "I couldn't find relevant information in the knowledge base to answer your question."

        # Build context string with citations
        context_parts = []
        for i, doc in enumerate(context, 1):
            content = doc.get("content", "")[:2000]  # Limit per doc
            source = doc.get("metadata", {}).get("filename", f"Source {i}")
            context_parts.append(f"[{i}] {source}:\n{content}")

        context_str = "\n\n---\n\n".join(context_parts)

        # Build prompt
        prompt = f"""Based on the following context from the knowledge base, answer the user's question.

CONTEXT:
{context_str}

USER QUESTION: {query}

Provide a comprehensive answer with citations [1], [2], etc. referencing the sources above."""

        # Get LLM response
        response = self.llm.invoke({"raw_data": [], "goal": prompt})

        return response.get("content", "Unable to generate response.")

    def research(self, query: str) -> dict:
        """Perform research on a query.

        Args:
            query: Research question

        Returns:
            Dict with answer, sources, and metadata
        """
        # Step 1: Search knowledge base
        context = self.search(query)

        # Step 2: Synthesize answer
        answer = self.synthesize(query, context)

        # Step 3: Build response
        sources = []
        for i, doc in enumerate(context, 1):
            sources.append({
                "id": f"[{i}]",
                "filename": doc.get("metadata", {}).get("filename", "Unknown"),
                "score": round(doc.get("score", 0), 3),
                "snippet": doc.get("content", "")[:200] + "...",
            })

        # Add to history
        self.history.append({
            "query": query,
            "answer": answer,
            "sources": sources,
        })

        return {
            "query": query,
            "answer": answer,
            "sources": sources,
            "context_count": len(context),
        }

    def follow_up(self, query: str) -> dict:
        """Handle follow-up question with conversation context.

        Args:
            query: Follow-up question

        Returns:
            Research response
        """
        # Include previous context in search
        if self.history:
            last = self.history[-1]
            augmented_query = f"{last['query']} {query}"
        else:
            augmented_query = query

        return self.research(augmented_query)

    def clear_history(self):
        """Clear conversation history."""
        self.history = []


def check_api_keys():
    """Check required API keys."""
    missing = []
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")

    if missing:
        print("Error: Missing environment variables:")
        for key in missing:
            print(f"  - {key}")
        sys.exit(1)


def interactive_mode(agent: ResearchAgent):
    """Run agent in interactive mode."""
    print("\n" + "=" * 60)
    print("Research Agent - Interactive Mode")
    print("=" * 60)
    print("\nCommands:")
    print("  /clear  - Clear conversation history")
    print("  /stats  - Show index statistics")
    print("  /quit   - Exit")
    print("\nAsk questions about your indexed documents.")
    print("-" * 60)

    while True:
        try:
            query = input("\n📝 You: ").strip()

            if not query:
                continue

            if query.lower() == "/quit":
                print("\nGoodbye!")
                break

            if query.lower() == "/clear":
                agent.clear_history()
                print("✓ History cleared")
                continue

            if query.lower() == "/stats":
                try:
                    stats = agent.store.describe_index()
                    print(f"\nIndex: {stats['index_name']}")
                    print(f"Total vectors: {stats['total_vector_count']}")
                    if stats.get('namespaces'):
                        for ns, data in stats['namespaces'].items():
                            marker = "→" if ns == agent.namespace else " "
                            print(f"  {marker} {ns}: {data['vector_count']} vectors")
                except Exception as e:
                    print(f"Error getting stats: {e}")
                continue

            # Research
            print("\n🔍 Searching knowledge base...")
            result = agent.research(query)

            print(f"\n🤖 Agent:\n")
            print(result["answer"])

            if result["sources"]:
                print("\n📚 Sources:")
                for src in result["sources"]:
                    print(f"  {src['id']} {src['filename']} (score: {src['score']})")

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")


def single_query(agent: ResearchAgent, query: str, verbose: bool = False):
    """Run single query."""
    print("\n" + "=" * 60)
    print("Research Agent - OpenBench")
    print("=" * 60)
    print(f"\nQuery: {query}")
    print(f"Index: {agent.index_name}/{agent.namespace}")
    print("-" * 60)

    print("\n🔍 Searching knowledge base...")
    result = agent.research(query)

    print(f"\n📊 Found {result['context_count']} relevant documents")

    print("\n" + "-" * 60)
    print("Answer:")
    print("-" * 60)
    print(result["answer"])

    if result["sources"]:
        print("\n" + "-" * 60)
        print("Sources:")
        print("-" * 60)
        for src in result["sources"]:
            print(f"\n{src['id']} {src['filename']}")
            print(f"   Score: {src['score']}")
            if verbose:
                print(f"   Snippet: {src['snippet']}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Research Agent - Query knowledge base with RAG"
    )
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("--index", default="openbench", help="Pinecone index name")
    parser.add_argument("--namespace", default="knowledge-base", help="Pinecone namespace")
    parser.add_argument("--model", default="gemini-2.5-flash", help="LLM model")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to retrieve")
    parser.add_argument("--min-score", type=float, default=0.7, help="Minimum similarity score")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    check_api_keys()

    # Create agent
    agent = ResearchAgent(
        index_name=args.index,
        namespace=args.namespace,
        model=args.model,
        top_k=args.top_k,
        min_score=args.min_score,
    )

    if args.interactive:
        interactive_mode(agent)
    elif args.query:
        single_query(agent, args.query, args.verbose)
    else:
        parser.print_help()
        print("\nExamples:")
        print('  python research_agent.py "What are the main findings?"')
        print('  python research_agent.py --interactive')


if __name__ == "__main__":
    main()
