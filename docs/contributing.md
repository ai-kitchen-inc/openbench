# Contributing

OpenBench welcomes documentation, tests, bug fixes, examples, and feature work. For larger changes, open an issue or discussion before implementing so the design can be reviewed.

## Contributor Checklist

- Read the files you plan to modify before editing.
- Search for existing patterns and helpers before adding new abstractions.
- Verify imports, class names, and method signatures from the repository.
- Add or update tests for behavior changes.
- Run the relevant Python tests and any integration checks for the area you touched.
- Keep commits focused and use conventional prefixes such as `feat:`, `fix:`, `docs:`, `refactor:`, and `test:`.

## Local Workflow

```bash
git clone https://github.com/ai-kitchen-inc/openbench.git
cd openbench
python -m pip install -e ".[dev]"
python -m unittest discover tests -v
```

For Open WebUI work:

```powershell
cd studio\open-webui
Copy-Item .env.example .env
docker compose --env-file .env up
```

## Documentation Contributions

Documentation lives under `docs/` and is built with Sphinx + MyST Markdown.

```bash
python -m pip install -r docs/requirements.txt
cd docs
make html
```

Avoid placeholder pages. Prefer short, verified examples that point to runnable files in `examples/` or public modules in `src/openbench/`.

## Code Of Conduct

See `CODE_OF_CONDUCT.md` for community expectations.

## Existing Guide

The repository also includes a longer contributor guide at `CONTRIBUTING.md`.
