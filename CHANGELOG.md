# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
See [docs/VERSIONING.md](docs/VERSIONING.md) for the project's versioning policy.

## [Unreleased]

### Added
- Open-source governance and community health files: `SECURITY.md`,
  `SUPPORT.md`, `GOVERNANCE.md`, `MAINTAINERS.md`, `CODEOWNERS`, `COMMUNITY.md`,
  `CITATION.cff`, `RELEASING.md`, `ROADMAP.md`.
- GitHub automation under `.github/`: CI workflow, issue/PR templates,
  Dependabot config, OpenSSF Scorecard workflow.
- PEP 561 `py.typed` marker so the shipped package is type-checkable by
  consumers.
- Coverage configuration (`[tool.coverage]`) and a shared test fixtures
  scaffold (`tests/conftest.py`, `tests/fixtures/`).
- Versioning, releasing, and OpenSSF badge tracking docs.

### Changed
- Package version is now sourced from a single location
  (`src/openbench/_version.py`); `pyproject.toml` derives it dynamically and the
  CLI reads it from installed package metadata. No behavior change.
- `CONTRIBUTING.md` updated to reflect the actual toolchain (ruff, lefthook,
  pnpm) and local check commands.

## [0.1.0] - 2026-01-01

### Added
- Initial alpha release of the OpenBench SDK: core abstractions
  (DataSource, Agent, OutputGenerator), chainable workflow composition,
  L1/L2 layers, BaseAgent runtime, data/intelligence/output/chat layers,
  framework adapters, and the `@openbench/chat-ui` React SDK.

[Unreleased]: https://github.com/ai-kitchen-inc/openbench/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ai-kitchen-inc/openbench/releases/tag/v0.1.0
