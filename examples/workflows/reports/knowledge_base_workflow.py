"""
Knowledge Base Workflow - Complete RAG Pipeline

Demonstrates full OpenBench workflow pattern:
    1. Index: PDFSource -> PineconeStore (build knowledge base)
    2. Query: Query -> RAG -> Agent -> Response (research)

Uses proper L2 layer composition:
    DataLayer | IntelligenceLayer | OutputLayer

Usage:
    # Index documents
    python knowledge_base_workflow.py index ./docs/*.pdf --namespace my-kb

    # Query knowledge base
    python knowledge_base_workflow.py query "What is sustainability?" --namespace my-kb

    # Full pipeline: index then query
    python knowledge_base_workflow.py pipeline doc.pdf "Summarize the document"

Requires:
    - PINECONE_API_KEY
    - GOOGLE_API_KEY
"""

import argparse
import glob
import os
import sys
from pathlib import Path

from openbench.adapters import GoogleADKAdapter
from openbench.core.abstractions import Query
from openbench.core.layers import DataLayer, IntelligenceLayer, OutputLayer
from openbench.data.sources import PDFSource
from openbench.data.stores import PineconeStore
from openbench.data.stores.base import ChunkingConfig
from openbench.intelligence import GoogleEmbeddingProvider
from openbench.output.generators import MarkdownGenerator
from openbench.workflows import Workflow


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


def create_embedding_provider():
    """Create Google embedding provider."""
    return GoogleEmbeddingProvider(model="gemini-embedding-001")


def create_store(
    index_name: str = "openbench",
    namespace: str = "knowledge-base",
    embedding_provider=None,
) -> PineconeStore:
    """Create PineconeStore."""
    if embedding_provider is None:
        embedding_provider = create_embedding_provider()

    return PineconeStore(
        index_name=index_name,
        namespace=namespace,
        embedding_provider=embedding_provider,
        chunking_config=ChunkingConfig(chunk_size=1000, chunk_overlap=200),
        create_if_missing=True,
    )


def create_llm(goal: str = "") -> GoogleADKAdapter:
    """Create LLM adapter."""
    system_instruction = f"""You are a research assistant analyzing documents from a knowledge base.

Task: {goal}

Instructions:
1. Analyze the provided context carefully
2. Synthesize information into a clear response
3. Cite sources using [source-N] format
4. If information is missing, acknowledge it
5. Be comprehensive but concise
6. Format response in Markdown"""

    return GoogleADKAdapter(
        model="gemini-2.5-flash",
        system_instruction=system_instruction,
    )


# =============================================================================
# WORKFLOW 1: Index Documents
# =============================================================================


def index_workflow(
    pdf_paths: list[str],
    index_name: str = "openbench",
    namespace: str = "knowledge-base",
) -> dict:
    """Index PDF documents to Pinecone.

    Pipeline: PDFSource[] -> PineconeStore
    """
    print("\n" + "=" * 60)
    print("INDEX WORKFLOW")
    print("=" * 60)
    print(f"Index: {index_name}/{namespace}")
    print(f"Files: {len(pdf_paths)}")

    embedding_provider = create_embedding_provider()
    store = create_store(index_name, namespace, embedding_provider)

    results = []
    for pdf_path in pdf_paths:
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            print(f"  ✗ Not found: {pdf_path}")
            results.append({"file": pdf_path, "status": "error", "error": "not found"})
            continue

        print(f"\n  Processing: {pdf_file.name}")

        try:
            # Extract PDF
            source = PDFSource(path=str(pdf_file))
            raw_data = source.extract()
            raw_data.metadata["filename"] = pdf_file.name

            # Index to Pinecone
            source_id = store.index(raw_data)

            print(f"    ✓ Indexed: {len(raw_data.content):,} chars")
            results.append(
                {
                    "file": pdf_file.name,
                    "status": "success",
                    "source_id": source_id,
                    "chars": len(raw_data.content),
                }
            )

        except Exception as e:
            print(f"    ✗ Error: {e}")
            results.append({"file": pdf_file.name, "status": "error", "error": str(e)})

    # Summary
    success = len([r for r in results if r["status"] == "success"])
    print(f"\n  Indexed: {success}/{len(results)} files")

    return {"indexed": results, "total": len(results), "success": success}


# =============================================================================
# WORKFLOW 2: Query Knowledge Base (RAG)
# =============================================================================


def query_workflow(
    query: str,
    index_name: str = "openbench",
    namespace: str = "knowledge-base",
    top_k: int = 5,
    output_path: str | None = None,
) -> dict:
    """Query knowledge base with RAG.

    Pipeline: Query -> PineconeStore -> GoogleADK -> Response
    """
    print("\n" + "=" * 60)
    print("QUERY WORKFLOW")
    print("=" * 60)
    print(f"Query: {query}")
    print(f"Index: {index_name}/{namespace}")

    embedding_provider = create_embedding_provider()
    store = create_store(index_name, namespace, embedding_provider)

    # Step 1: Search knowledge base
    print("\n[1/3] Searching knowledge base...")
    search_query = Query(text=query, limit=top_k)
    search_result = store.search(search_query)

    print(f"  Found: {len(search_result.items)} relevant documents")

    if not search_result.items:
        return {
            "query": query,
            "answer": "No relevant documents found in the knowledge base.",
            "sources": [],
        }

    # Step 2: Build context
    print("\n[2/3] Building context...")
    context_parts = []
    sources = []

    for i, item in enumerate(search_result.items):
        content = item.get("content", "")[:2000]
        filename = item.get("metadata", {}).get("filename", f"Source-{i + 1}")
        score = search_result.scores[i] if search_result.scores else 0

        context_parts.append(f"[{i + 1}] {filename}:\n{content}")
        sources.append(
            {
                "id": f"[{i + 1}]",
                "filename": filename,
                "score": round(score, 3),
            }
        )

    context = "\n\n---\n\n".join(context_parts)
    print(f"  Context: {len(context):,} chars from {len(sources)} sources")

    # Step 3: Generate response with LLM
    print("\n[3/3] Generating response...")
    llm = create_llm(query)

    prompt = f"""Based on the following context from the knowledge base, answer the question.

CONTEXT:
{context}

QUESTION: {query}

Provide a comprehensive answer with citations [1], [2], etc."""

    # Create mock raw_data for the adapter
    mock_raw = type("MockRaw", (), {"content": prompt})()
    response = llm.invoke({"raw_data": [mock_raw], "goal": query})

    answer = response.get("content", "Unable to generate response.")

    # Step 4: Output (optional)
    if output_path:
        output_content = f"""# Research: {query}

## Answer

{answer}

## Sources

"""
        for src in sources:
            output_content += f"- {src['id']} {src['filename']} (score: {src['score']})\n"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(output_content)
        print(f"\n  Output saved: {output_path}")

    print("\n" + "-" * 60)
    print("ANSWER:")
    print("-" * 60)
    print(answer)

    print("\n" + "-" * 60)
    print("SOURCES:")
    print("-" * 60)
    for src in sources:
        print(f"  {src['id']} {src['filename']} (score: {src['score']})")

    return {
        "query": query,
        "answer": answer,
        "sources": sources,
    }


# =============================================================================
# WORKFLOW 3: Full Pipeline (Index + Query)
# =============================================================================


def pipeline_workflow(
    pdf_path: str,
    query: str,
    index_name: str = "openbench",
    namespace: str = "pipeline",
    output_path: str = "output/research_result.md",
) -> dict:
    """Full pipeline: Index PDF then Query.

    Uses OpenBench Workflow pattern:
        DataLayer(PDFSource, PineconeStore)
        | IntelligenceLayer(GoogleADK)
        | OutputLayer(MarkdownGenerator)
    """
    print("\n" + "=" * 60)
    print("FULL PIPELINE WORKFLOW")
    print("=" * 60)
    print(f"PDF: {pdf_path}")
    print(f"Query: {query}")
    print(f"Output: {output_path}")

    # Components
    pdf_source = PDFSource(path=pdf_path)
    embedding_provider = create_embedding_provider()
    store = create_store(index_name, namespace, embedding_provider)
    llm = create_llm(query)
    output_gen = MarkdownGenerator(output_path=output_path)

    # Build workflow using L2 layers
    workflow = Workflow(
        name="knowledge-base-pipeline",
        chain=(
            DataLayer(sources=pdf_source, stores=[store])
            | IntelligenceLayer(agents=llm)
            | OutputLayer(generators=output_gen)
        ),
        checkpoints=True,
    )

    print("\nWorkflow: DataLayer | IntelligenceLayer | OutputLayer")
    print("-" * 60)

    # Run workflow
    result = workflow.run(
        {
            "goal": query,
            "output_path": output_path,
            "title": f"Research: {query}",
        }
    )

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)

    if result.get("generated_outputs"):
        output = result["generated_outputs"][0]
        print(f"  Output: {output.file_path}")
        print(f"  Size: {output.size_bytes} bytes")

    return result


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Knowledge Base Workflow - Index and Query documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index PDFs
  python knowledge_base_workflow.py index doc1.pdf doc2.pdf
  python knowledge_base_workflow.py index ./docs/*.pdf --namespace my-kb

  # Query
  python knowledge_base_workflow.py query "What is the main topic?"
  python knowledge_base_workflow.py query "Summarize findings" -o result.md

  # Full pipeline
  python knowledge_base_workflow.py pipeline doc.pdf "Summarize this document"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Index command
    index_parser = subparsers.add_parser("index", help="Index PDF documents")
    index_parser.add_argument("pdfs", nargs="+", help="PDF files or glob pattern")
    index_parser.add_argument("--index", default="openbench")
    index_parser.add_argument("--namespace", default="knowledge-base")

    # Query command
    query_parser = subparsers.add_parser("query", help="Query knowledge base")
    query_parser.add_argument("query", help="Research query")
    query_parser.add_argument("--index", default="openbench")
    query_parser.add_argument("--namespace", default="knowledge-base")
    query_parser.add_argument("--top-k", type=int, default=5)
    query_parser.add_argument("-o", "--output", help="Output file path")

    # Pipeline command
    pipe_parser = subparsers.add_parser("pipeline", help="Full pipeline: index + query")
    pipe_parser.add_argument("pdf", help="PDF file to process")
    pipe_parser.add_argument("query", help="Research query")
    pipe_parser.add_argument("--index", default="openbench")
    pipe_parser.add_argument("--namespace", default="pipeline")
    pipe_parser.add_argument("-o", "--output", default="output/research_result.md")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    check_api_keys()

    if args.command == "index":
        # Expand glob patterns
        pdf_files = []
        for pattern in args.pdfs:
            if "*" in pattern:
                pdf_files.extend(glob.glob(pattern))
            else:
                pdf_files.append(pattern)

        index_workflow(pdf_files, args.index, args.namespace)

    elif args.command == "query":
        query_workflow(
            args.query,
            args.index,
            args.namespace,
            args.top_k,
            args.output,
        )

    elif args.command == "pipeline":
        pipeline_workflow(
            args.pdf,
            args.query,
            args.index,
            args.namespace,
            args.output,
        )


if __name__ == "__main__":
    main()
