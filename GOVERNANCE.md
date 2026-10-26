# Project Governance

This document describes how the OpenBench project is governed and how
decisions are made. It is intentionally lightweight to match the project's
current stage, and will evolve as the community grows.

## Roles

### Contributors

Anyone who contributes code, documentation, tests, issues, or reviews. No
formal status is required — opening a pull request makes you a contributor.

### Maintainers

Contributors with write access who are responsible for reviewing and merging
pull requests, triaging issues, and stewarding the roadmap. The current
maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md) and codified for
review routing in [.github/CODEOWNERS](.github/CODEOWNERS).

### Becoming a maintainer

A contributor may be invited to become a maintainer after a sustained track
record of high-quality contributions and reviews. Existing maintainers
nominate candidates; the nomination passes by **lazy consensus** (no
objections within 5 business days) of the current maintainers.

## Decision Making

OpenBench uses **lazy consensus**. Most changes proceed without a formal vote:

1. Routine changes (bug fixes, docs, tests) require **one maintainer approval**
   and passing CI to merge.
2. Substantial changes (new public APIs, dependencies, breaking changes)
   should start with a GitHub Discussion or issue. They require **two
   maintainer approvals** and a 3-day comment window.
3. If consensus cannot be reached, a simple majority vote of maintainers
   decides. In a tie, the change is **not** adopted (status quo wins).

## Code Review & Merge Policy

- All changes land via pull request — no direct pushes to `main`.
- CI (lint, type check, tests) must pass before merge. See
  [.github/workflows/ci.yml](.github/workflows/ci.yml).
- At least one maintainer approval is required; the author may not be the sole
  approver.
- **Branch protection** on `main` (required status checks, required review,
  linear history) is a repository-admin setting that maintainers are expected
  to keep enabled. This is a manual GitHub setting, not a committed file.

## Releases

Releases follow [Semantic Versioning](docs/VERSIONING.md) and the process in
[RELEASING.md](RELEASING.md). Any maintainer may cut a release once `main` is
green and the [CHANGELOG.md](CHANGELOG.md) is updated.

## Code of Conduct

All participation is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md). Enforcement is handled by the
maintainers.

## Changes to Governance

Changes to this document follow the same substantial-change process described
above (two maintainer approvals, 3-day window).
