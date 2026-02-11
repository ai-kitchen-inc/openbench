<div align="center">

```
 ██████╗ ██████╗ ███████╗███╗   ██╗██████╗ ███████╗███╗   ██╗ ██████╗██╗  ██╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔════╝████╗  ██║██╔════╝██║  ██║
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██████╔╝█████╗  ██╔██╗ ██║██║     ███████║
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██╗██╔══╝  ██║╚██╗██║██║     ██╔══██║
╚██████╔╝██║     ███████╗██║ ╚████║██████╔╝███████╗██║ ╚████║╚██████╗██║  ██║
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝
```

### The Open Source Agentic AI Workbench

**Build. Orchestrate. Export. Scale.**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![GitHub Stars](https://img.shields.io/github/stars/ai-kitchen-inc/openbench?style=social)](https://github.com/ai-kitchen-inc/openbench)

[Documentation](docs/README.md) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [Examples](#-use-cases) • [Contributing](CONTRIBUTING.md)

</div>

---

## 🚀 What is OpenBench?

OpenBench is the **open source workbench for the agentic AI era**. It's not just another AI tool—it's a complete platform that transforms how you work with data, intelligence, and outputs.

Think of it as your **AI-native operating system** for knowledge work:

- **Ingest anything**: PDFs, APIs, web search—if it contains information, OpenBench can work with it
- **Agent-powered workflows**: Author sophisticated agentic flows that actually get work done
- **Export everywhere**: Turn insights into presentations, reports, markdown, or raw data

Built for developers, data scientists, and organizations that refuse to compromise on flexibility, privacy, or control.

## 🎯 Why OpenBench?

The AI landscape is fragmented. You have:
- Data locked in silos
- AI models that can't access your actual work
- No way to orchestrate complex workflows
- Outputs that don't match how you need to communicate

**OpenBench unifies everything.**

```
Data Sources → Intelligent Processing → Beautiful Outputs
```

### 🔌 Universal Control Plane

**OpenBench is not another framework. It's the control plane that connects them all.**

Bring your own agents from ANY framework:
- **LangChain** - Wrap any LangChain Runnable
- **AG2 (AutoGen)** - Use your existing AG2 agents
- **CrewAI** - Integrate role-based agent crews
- **Google ADK** - Connect Google's agent framework
- **E2B** - Run custom code in sandboxed environments

```python
from openbench.adapters.langchain import LangChainAdapter
from openbench.data.sources import PDFSource
from openbench.output.generators import PDFGenerator
from openbench import Workflow

# Your existing LangChain agent
my_langchain_agent = AgentExecutor(...)

# Use it in OpenBench
workflow = Workflow(
    name="langchain-report",
    chain=(
        PDFSource("./documents/report.pdf")    # OpenBench data layer
        | LangChainAdapter(my_langchain_agent)  # Your LangChain agent
        | PDFGenerator()                        # OpenBench output layer
    )
)
result = workflow.run()
```

**No rewrites. No lock-in. Pure interoperability.**

---

## Implementation Status

**Version**: 0.1.0 (Alpha) | Core Complete, Providers In Progress

| Phase | Status |
|-------|--------|
| **Phase 1: Core Abstractions** | Complete - Interfaces, plugin registry, DAG workflows, state management |
| **Phase 2: Infrastructure** | Complete - Provider Service, Config, Agent interface, L2 layers, 508 tests |
| **Phase 3: Providers** | In Progress - LLM (OpenAI, Anthropic), Vector (ChromaDB, Pinecone), Output (ReportLab, python-pptx) |

```bash
pip install -e ".[all]" && python examples/workflows/reports/sustainability_report.py
```

---

## Workflow API

```python
from openbench.workflows import Workflow

workflow = Workflow(
    name="sustainability-report",
    chain=(
        (data_source1 & data_source2 & data_source3)  # Parallel
        | research | analysis                          # Sequential
        | (pdf_generator & pptx_generator)             # Parallel
    ),
    checkpoints=True
)
result = workflow.run({"project": "Q1 2026"})
```

**Features:** DAG composition (`|` sequential, `&` parallel), L1/L2 orchestration, automatic checkpointing.

---

All open source. All extensible. All yours.

## Quick Start

```bash
git clone https://github.com/ai-kitchen-inc/openbench.git && cd openbench
pip install -e ".[all]"
python examples/workflows/reports/sustainability_report.py
```

```python
from openbench import DataLayer, IntelligenceLayer, OutputLayer
from openbench.data.sources import PDFSource
from openbench.intelligence.agents import ResearchAgent
from openbench.output.generators import PDFGenerator

# Compose layers with pipe operators
workflow = (
    DataLayer(sources=PDFSource("./documents/report.pdf"))
    | IntelligenceLayer(agents=ResearchAgent(goal="Analyze Q4 sales"))
    | OutputLayer(generators=PDFGenerator())
)
result = workflow.invoke({"goal": "Q4 Sales Analysis"})
```

## Architecture

Three layers working in harmony:

**Data Layer** - Connect to any source: PDFs, databases, APIs, multimedia. Access via REST, MCP, or native SDKs.

**Intelligence Layer** - Build AI agents: Research, Analysis, Content, Action. Multi-agent coordination with human-in-the-loop support.

**Output Layer** - Export anywhere: PDF, PowerPoint, Markdown, Audio, Dashboards.

```python
from openbench import Workflow
from openbench.intelligence.agents import ResearchAgent, AnalysisAgent, ContentAgent
from openbench.output.generators import PDFGenerator, PowerPointGenerator

# Chain agents sequentially, output in parallel
workflow = Workflow(
    name="strategic-analysis",
    chain=(
        ResearchAgent(goal="Competitive intelligence")
        | AnalysisAgent(goal="Market gaps")
        | ContentAgent(goal="Strategic memo")
        | (PDFGenerator() & PowerPointGenerator())
    ),
    checkpoints=True
)
result = workflow.run({"goal": "Strategic Analysis"})
```

---

## 💡 Use Cases

### 📚 Automated Research & Analysis
```
Ingest academic papers + news + data → Research agent → Comprehensive literature review
```

### 📊 Business Intelligence
```
SQL database + CRM API + Market data → Analysis workflow → Executive dashboards
```

### 🎓 Educational Content
```
Course materials + Videos → Content agents → Interactive lessons + Quizzes + Presentations
```

### 🏢 Enterprise Knowledge Management
```
Confluence + Drive + Slack → Semantic search → Instant answers + Auto-documentation
```

### 🎬 Content Creation Pipeline
```
Research data + Brand guidelines → Multi-agent workflow → Blog + Video + Social media
```

## Tech Stack

Python, Click, Pydantic, Google GenAI, LangChain, CrewAI, AG2, Pinecone, ReportLab, python-pptx.

## Features

- **Privacy-First**: Self-hosted, zero lock-in, credential encryption
- **Model Agnostic**: OpenAI, Anthropic, open source models
- **Enterprise Ready**: Centralized config, encryption, audit ready
- **Extensible**: Plugin registry with decorators and auto-discovery
- **Composable**: DAG workflows with `|` and `&` operators
- **Well-Tested**: 508 tests

## 🗺️ Roadmap

- [ ] **Q1 2026**: Voice-first interface for agent interaction
- [ ] **Q2 2026**: Real-time collaborative workflows
- [ ] **Q2 2026**: Marketplace for community agents and templates
- [ ] **Q3 2026**: Edge deployment for air-gapped environments
- [ ] **Q4 2026**: Multi-modal agent support (vision, audio, code)

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Linting & formatting (Ruff - all-in-one)
ruff check src/ tests/       # Lint
ruff check --fix src/ tests/  # Lint + auto-fix
ruff format src/ tests/       # Format

# Setup pre-commit hooks (runs ruff automatically on git commit)
pre-commit install

# Run tests
python -m unittest discover tests -v

# Run tests with coverage
pytest tests/ --cov=openbench --cov-report=term-missing
```

## Contributing

[Report bugs](https://github.com/ai-kitchen-inc/openbench/issues) | [Request features](https://github.com/ai-kitchen-inc/openbench/discussions) | [Submit PRs](CONTRIBUTING.md) | [Join Discord](https://discord.com/users/openbench.ai)

## 📄 License

OpenBench is open source software licensed under the [Apache License 2.0](LICENSE).

Free to use, modify, and distribute. Forever.

## Community

[Documentation](docs/README.md) | [Discord](https://discord.com/users/openbench.ai) | [Discussions](https://github.com/ai-kitchen-inc/openbench/discussions) | [Email](mailto:openbench2026@gmail.com)

---

<div align="center">

**Built with ❤️ by the OpenBench community**

*Making agentic AI accessible to everyone*

[Get Started](#-quick-start) • [Documentation](docs/README.md) • [Community](#-community--support)

</div>
