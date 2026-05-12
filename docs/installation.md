# Installation

OpenBench is a Python package with optional extras for provider SDKs, data processing, chat serving, and output generation.

## Requirements

- Python `>=3.10`.
- Python 3.10, 3.11, or 3.12 is recommended for development.
- Node.js and `pnpm` are required only when working on `studio/chat-ui` or frontend examples.

## Install From A Checkout

```bash
git clone https://github.com/ai-kitchen-inc/openbench.git
cd openbench
python -m pip install -e .
```

## Install Optional Extras

The available extras are defined in `pyproject.toml`:

```bash
python -m pip install -e ".[dev]"
python -m pip install -e ".[data]"
python -m pip install -e ".[intelligence]"
python -m pip install -e ".[google]"
python -m pip install -e ".[search]"
python -m pip install -e ".[output]"
python -m pip install -e ".[security]"
python -m pip install -e ".[vector]"
python -m pip install -e ".[chat]"
python -m pip install -e ".[all]"
```

Use `.[all]` for broad local experimentation. For production, install only the integrations your application needs.

## Verify The Install

```bash
python -c "import openbench; print(openbench.__version__)"
openbench --version
```

On Windows terminals using a legacy code page, Click help that includes icons may require UTF-8 output:

```powershell
$env:PYTHONUTF8 = "1"
openbench --help
```

## Documentation Dependencies

To build this documentation locally:

```bash
python -m pip install -r docs/requirements.txt
cd docs
make html
```
