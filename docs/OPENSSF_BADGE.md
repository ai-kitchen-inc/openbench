# OpenSSF Best Practices Badge — Tracking

This document tracks OpenBench's progress toward the
[OpenSSF Best Practices Badge](https://www.bestpractices.dev/) (formerly CII
Best Practices). Register the project at
<https://www.bestpractices.dev/> and link the badge in `README.md` once the
passing level is reached.

Legend: ✅ met · 🚧 partial · 📋 not started

## Basics

- ✅ Project has a public version-controlled source repository (GitHub).
- ✅ Project uses an OSI-approved license (Apache-2.0, see [LICENSE](../LICENSE)).
- ✅ Project has a `README` describing what it does and how to get started.
- ✅ Contribution process documented ([CONTRIBUTING.md](../CONTRIBUTING.md)).
- ✅ Code of Conduct present ([CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)).

## Reporting & security

- ✅ Vulnerability reporting process documented ([SECURITY.md](../SECURITY.md)).
- ✅ Private reporting channel (GitHub Security Advisories + email).
- ✅ Bug reporting process documented (issue templates).

## Quality & testing

- ✅ Automated test suite exists (`tests/`, 759 tests).
- 🚧 CI runs the test suite on every PR (see
  [.github/workflows/ci.yml](../.github/workflows/ci.yml)) — verify required
  status checks are enforced via branch protection.
- ✅ Static analysis enforced in CI (ruff + mypy).
- 🚧 Test coverage measured and published (coverage config added; publish a
  badge once a coverage service is wired up).

## Change control & releases

- ✅ Semantic Versioning policy ([docs/VERSIONING.md](VERSIONING.md)).
- ✅ Release process documented ([RELEASING.md](../RELEASING.md)).
- 📋 Signed releases (`git tag -s`) and build provenance/attestations.

## Supply chain

- 🚧 Dependency update automation (Dependabot —
  [.github/dependabot.yml](../.github/dependabot.yml)).
- 🚧 Dependency vulnerability scanning (`pip-audit` in CI; Dependabot alerts).
- 📋 OpenSSF Scorecard workflow (added at
  [.github/workflows/scorecard.yml](../.github/workflows/scorecard.yml)) — review
  the score and address findings.

## Next actions

1. Enable branch protection on `main` with CI as a required status check.
2. Wire coverage reporting to a service and add the badge.
3. Adopt signed tags and provenance for releases.
4. Register the project on bestpractices.dev and fill in the questionnaire.
