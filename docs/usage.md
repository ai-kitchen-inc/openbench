# Usage Guide

OpenBench applications are built by composing small units into workflows.

## Core Composition

The base composition API lives in `openbench.core.chainable`:

- `Chainable`: interface for objects with `invoke()`.
- `Chain`: sequential execution.
- `Parallel`: fan-out execution over several branches.
- `Conditional`: choose between two branches.
- `Router`: choose among named routes.
- `Lambda`: wrap a Python callable as a chainable step.
- `Passthrough`: return input unchanged.

```python
from openbench.core import Lambda, Parallel

normalize = Lambda(lambda text: text.strip(), name="normalize")
words = Lambda(lambda text: text.split(), name="words")
length = Lambda(lambda text: len(text), name="length")

workflow = normalize | (words & length)
print(workflow.invoke(" OpenBench "))
```

## Data Layer

Data sources implement `DataSource` and return `RawData`. Built-in source modules include PDF extraction, grounded search, and LangExtract-based structured extraction. Store utilities include chunking helpers, `PineconeStore`, and hybrid search mixins.

```python
from openbench.data import PDFSource

source = PDFSource("docs/example.pdf")
raw = source.extract()
```

Optional dependencies may be required for specific source or store implementations.

## Intelligence Layer

The intelligence layer includes:

- `BaseAgent`, `SimpleAgent`, and `StructuredOutputAgent`.
- Specialized agents such as `ResearchAgent`, `AnalysisAgent`, `ContentAgent`, `ActionAgent`, and `MetaAgent`.
- `GeminiLLMProvider`, embedding providers, planning helpers, tool execution, RAG helpers, memory, personas, and skills.

Personas can be loaded from a directory containing `SOUL.md`, `STYLE.md`, and `AGENTS.md`. Skills are directories with `SKILL.md`, optional references, and optional `tools.py`.

## Chat Layer

`openbench.chat` provides a backend for interactive chat applications:

- `ChatEngine` orchestrates sessions, agents, and renderers.
- A2UI v0.10 builders produce structured UI messages.
- Content renderers translate text, charts, tables, files, forms, media, tabs, modals, code, lists, and callouts.
- AG-UI transport streams server-sent events and handles REST actions.
- OpenAI-compatible transport exposes `/v1/models` and `/v1/chat/completions` for Open WebUI.

The bundled React SDK has been excluded from the active UI path. Use
`studio/open-webui` and mount `create_openai_compatible_router(...)` from your
FastAPI backend with `app.include_router(..., prefix="/v1")`.

## Output Layer

Output generation classes implement `OutputGenerator` and return `GeneratedOutput`. Current generator modules include PDF, Markdown, PowerPoint, dashboard, and audio generator classes. Some formats need optional dependencies such as `reportlab` or `python-pptx`.

## Framework Adapters

OpenBench can wrap external framework objects through adapters:

- `LangChainAdapter`
- `CrewAIAdapter`
- `AG2Adapter`
- `E2BAdapter`
- `GoogleADKAdapter`

Adapters make existing agents or runtimes usable inside OpenBench workflows without rewriting the external framework code.
