# Development Setup

This page covers local development for the Python SDK, documentation, and Open WebUI integration.

## Python SDK

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix/macOS: source .venv/bin/activate

python -m pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m unittest discover tests -v
pytest tests/
```

Run quality checks:

```bash
ruff check src tests
mypy src/openbench
```

## Documentation

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

The generated HTML is written to `docs/_build/html/`.

## Open WebUI

The active chat UI path is Open WebUI connected to OpenBench through the
OpenAI-compatible chat transport.

```powershell
cd studio\open-webui
Copy-Item .env.example .env
docker compose --env-file .env up
```

The old `studio/chat-ui` React SDK is excluded for now and kept only as a
migration note.

## Working With Optional Integrations

Many integrations are optional. Install the matching extra before running provider-specific tests or examples:

```bash
python -m pip install -e ".[google]"
python -m pip install -e ".[vector]"
python -m pip install -e ".[chat]"
```

Unit tests should mock external APIs and avoid making real provider calls.
