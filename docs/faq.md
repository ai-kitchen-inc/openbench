# FAQ And Troubleshooting

## Which Python versions are supported?

`pyproject.toml` declares Python `>=3.10`. Python 3.10, 3.11, and 3.12 are recommended for development and ReadTheDocs builds.

## Do I need all optional extras?

No. Install the core package first, then add extras for the integrations you use. `.[all]` is convenient for local exploration but can be heavy for deployment.

## Why do some examples require API keys?

Examples that call real LLMs, embedding APIs, search APIs, or vector stores require the corresponding provider credentials, such as `GOOGLE_API_KEY` or `PINECONE_API_KEY`. Core composition and adapter demos use mock objects and can run without keys.

## Where does OpenBench store local state?

Provider and general configuration use `~/.openbench/`. Workflow state defaults depend on the workflow and state store configuration. `LocalStorageBackend` also defaults to `~/.openbench/`.

## Why does `openbench --help` fail on my Windows terminal?

Some Windows shells default to a legacy code page that cannot print icon characters in Click help. Enable UTF-8 output:

```powershell
$env:PYTHONUTF8 = "1"
openbench --help
```

## How do I build the docs?

```bash
python -m pip install -e .
python -m pip install -r docs/requirements.txt
cd docs
make html
```

On Windows:

```powershell
cd docs
.\make.bat html
```

## How do I debug import errors in docs builds?

Install the package in editable mode first. If an optional provider dependency is missing, either install the matching extra or add it to `autodoc_mock_imports` in `docs/conf.py` when the dependency should not be required for documentation builds.
