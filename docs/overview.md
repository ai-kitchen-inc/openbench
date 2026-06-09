# Project Overview

OpenBench is a workflow orchestrator, agent runtime, and control plane for AI workflows. It is designed around composable Python objects that implement `invoke()` and can be connected with the pipe (`|`) and parallel (`&`) operators.

## What OpenBench Provides

- **Workflow composition** with `Chainable`, `Chain`, `Parallel`, `Conditional`, `Router`, and `Workflow`.
- **Three system layers**: `DataLayer`, `IntelligenceLayer`, and `OutputLayer`.
- **Built-in agent runtime** through `BaseAgent`, tool execution, memory, planning, RAG helpers, personas, and skills.
- **Framework adapters** for LangChain, CrewAI, AG2, E2B, and Google ADK.
- **Data and storage abstractions** for sources, stores, chunking, embeddings, and search.
- **Chat layer** with `ChatEngine`, AG-UI transport, A2UI v0.10 message building, content renderers, and a React SDK in `studio/chat-ui`.
- **Output generation** for PDF, Markdown, PowerPoint, dashboards, and audio workflows.

## Package Status

The package metadata currently declares version `0.1.0` and Python `>=3.10`. The repository includes many optional integrations. Install only the extras you need for local development or deployment.

## Repository Map

- `src/openbench/core/`: shared abstractions, registries, config, providers, layers, storage, and workflow state.
- `src/openbench/data/`: data sources, stores, chunking, and search utilities.
- `src/openbench/intelligence/`: agents, LLM providers, embeddings, memory, personas, skills, planning, and scratchpads.
- `src/openbench/chat/`: chat orchestration, sessions, A2UI, renderers, and AG-UI transport.
- `src/openbench/output/`: output generators and output factory helpers.
- `src/openbench/adapters/`: external framework adapters.
- `studio/chat-ui/`: TypeScript React SDK for OpenBench chat interfaces.
- `examples/`: runnable workflows and applications.
- `tests/`: Python test suite plus frontend tests under `studio/chat-ui/tests/`.
