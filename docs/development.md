# Development Setup

This page covers local development for the Python SDK, documentation, and chat UI package.

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

## Chat UI SDK

The frontend SDK is a TypeScript/React package in `studio/chat-ui`.

```bash
cd studio/chat-ui
pnpm install
pnpm build
pnpm typecheck
pnpm test:run
pnpm lint
```

The package exports React components, hooks, A2UI rendering utilities, and CSS.

## Working With Optional Integrations

Many integrations are optional. Install the matching extra before running provider-specific tests or examples:

```bash
python -m pip install -e ".[google]"
python -m pip install -e ".[vector]"
python -m pip install -e ".[chat]"
```

Unit tests should mock external APIs and avoid making real provider calls.
