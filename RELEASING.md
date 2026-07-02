# Releasing OpenBench

This document describes how maintainers cut a release. OpenBench ships two
artifacts: the Python SDK (`openbench` on PyPI) and the frontend SDK
(`@openbench/chat-ui` on npm). Versioning follows
[docs/VERSIONING.md](docs/VERSIONING.md).

## Prerequisites

- You are a maintainer with publish rights (PyPI and/or npm).
- `main` is green (CI passing).
- You have the build tooling installed: `python -m pip install build twine`
  for Python and `pnpm` for the frontend.

## Python SDK release

1. **Bump the version.** Edit the single source of truth:
   `src/openbench/_version.py`. `pyproject.toml` derives the version
   dynamically — do **not** edit it for the version.
2. **Update the changelog.** Move items from `[Unreleased]` into a new
   version section in [CHANGELOG.md](CHANGELOG.md) with today's date, and
   update the comparison links at the bottom.
3. **Open a release PR** titled `chore(release): vX.Y.Z` and merge once
   approved and green.
4. **Tag the release:**
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```
5. **Build and verify:**
   ```bash
   python -m build
   twine check dist/*
   ```
6. **Publish to PyPI:**
   ```bash
   twine upload dist/*
   ```
7. **Create a GitHub Release** from the tag, pasting the changelog section.

## Frontend SDK release (`studio/chat-ui`)

1. Bump `version` in `studio/chat-ui/package.json`.
2. Build and check:
   ```bash
   cd studio/chat-ui
   pnpm install
   pnpm typecheck
   pnpm test:run
   pnpm build
   ```
3. Publish:
   ```bash
   pnpm publish --access public
   ```

## After release

- Verify the published package installs cleanly in a fresh environment.
- Add a new `[Unreleased]` section to the changelog.
- Announce in [Discussions](https://github.com/ai-kitchen-inc/openbench/discussions)
  and Discord.

## Signing (recommended)

Sign release tags (`git tag -s`) and, where supported, publish with
attestations / provenance. Tracking item: see
[docs/OPENSSF_BADGE.md](docs/OPENSSF_BADGE.md).
