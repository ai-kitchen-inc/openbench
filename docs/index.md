# OpenBench Documentation

OpenBench is an open-source Python SDK for composing AI workflows across data sources, agents, framework adapters, chat interfaces, and output generators. It provides both workflow orchestration primitives and a built-in agent runtime, while keeping integrations swappable through adapters, registries, and provider configuration.

The documentation is built with Sphinx and MyST Markdown. It can be built locally with:

```bash
python -m pip install -e .
python -m pip install -r docs/requirements.txt
cd docs
make html
```

On Windows, use:

```powershell
cd docs
.\make.bat html
```

```{toctree}
:maxdepth: 2
:caption: Get Started

overview
installation
quickstart
usage
configuration
```

```{toctree}
:maxdepth: 2
:caption: Reference

cli
reference/index
ARCHITECTURE
CHAT_UI_ARCHITECTURE
STORAGE
DESIGN_SYSTEM
```

```{toctree}
:maxdepth: 2
:caption: Guides

examples
development
contributing
faq
CUSTOM-BACKEND
```

```{toctree}
:maxdepth: 1
:caption: Existing Markdown Reference

GETTING_STARTED
API
README
```
