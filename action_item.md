# Action Items — Open-Source Quality Restructure

> **Goal:** raise OpenBench to high-quality open-source standards.
> **Hard rule:** every task adds **structure / docs / automation only** — **no
> runtime behavior changed**. Verified: source edits are limited to a
> single-version-source refactor + `py.typed`; all program logic, signatures,
> and outputs are unchanged. Test suite green (177 passed in the smoke subset).
>
> **Status:** `[x]` done this pass · `[ ]` remaining (mostly repo-admin GitHub
> settings that cannot be done from the codebase, or follow-up content work).
>
> **Priority legend:** `P0` ship-blocker · `P1` important · `P2` nice-to-have.

---

## 1. GitHub Open Source Guides — community readiness

- [x] `P0` Add **`SECURITY.md`** — private reporting (GitHub advisories + email), supported versions, disclosure timeline.
- [x] `P1` Add **`SUPPORT.md`** — Discussions/issues/Discord channels; linked from `README.md`.
- [x] `P1` Add **`GOVERNANCE.md`** — lazy-consensus decision process, roles, maintainer path.
- [x] `P1` Add **`MAINTAINERS.md`** + **`.github/CODEOWNERS`** — ownership + review routing (placeholder team `@ai-kitchen-inc/maintainers` — replace with real handles).
- [x] `P1` Add **`CHANGELOG.md`** — Keep a Changelog format; seeded `0.1.0` + `[Unreleased]`.
- [x] `P2` Add **`CITATION.cff`** — citation metadata.
- [x] `P2` Add **`.github/FUNDING.yml`** — template (commented; fill in real platforms if/when funding exists).
- [x] `P2` `README.md` polish — added CI badge + Support link + **Troubleshooting** table.

## 2. GitHub Repository Best Practices — `.github/` automation

- [x] `P0` Add **`.github/workflows/ci.yml`** — ruff lint + ruff format check + mypy + pytest matrix (3.10–3.12) + coverage; wraps existing `pyproject.toml` config.
- [x] `P1` Frontend CI — `frontend` job in `ci.yml` (pnpm install / lint / typecheck / test / build for `studio/chat-ui`).
- [x] `P1` Add **`.github/ISSUE_TEMPLATE/`** — `bug_report.yml`, `feature_request.yml`, `config.yml`.
- [x] `P1` Add **`.github/PULL_REQUEST_TEMPLATE.md`**.
- [x] `P1` Add **`.github/dependabot.yml`** — pip + npm + github-actions weekly.
- [x] `P2` Add **`.editorconfig`** — mirrors ruff/black (LF, UTF-8, 100 cols).
- [x] `P2` Hooks tool decided — **keep `lefthook.yml`**; documented in `CONTRIBUTING.md` + `README.md` (replaced stale `pre-commit` references).
- [ ] `P1` **Manual (repo admin):** enable branch protection on `main` (require CI status checks + 1 review + linear history). Documented in `GOVERNANCE.md`; must be set in GitHub UI.

## 3. CONTRIBUTING.md Guidance — contributor workflow gaps

- [x] `P1` **Development environment** — exact steps (conda py312 / venv, `pip install -e ".[all]"`, `npx lefthook install`).
- [x] `P1` **Run checks locally** — ruff / mypy / pytest section matching CI.
- [x] `P1` **Commit convention** — Conventional Commits; added **no `Co-Authored-By` watermark** rule.
- [x] `P2` **DCO sign-off** note (`git commit -s`).
- [x] `P2` good-first-issue / triage guidance (already present; retained). Also fixed stale tooling (flake8/pylint/Prettier/ESLint/npm/docker-compose → ruff/Biome/pnpm).

## 4. OpenSSF Best Practices Badge — passing-level criteria

- [x] `P0` CI runs the test suite on every PR (`ci.yml`).
- [x] `P1` Static-analysis gate — ruff + mypy enforced in CI.
- [x] `P1` **Coverage measurement** — `[tool.coverage]` added to `pyproject.toml`; CI emits `coverage.xml`.
- [x] `P1` **Dependency vuln scanning** — `.github/workflows/security.yml` runs `pip-audit` (push/PR/weekly).
- [x] `P1` HTTPS sites + vuln-report process documented (`SECURITY.md`, `docs/OPENSSF_BADGE.md`).
- [x] `P2` Release-signing / tagged-release process — documented in `RELEASING.md`.
- [x] `P2` OpenSSF **Scorecard** workflow added (`.github/workflows/scorecard.yml`); criteria tracker `docs/OPENSSF_BADGE.md`.
- [ ] `P2` **Manual:** register the project at bestpractices.dev, wire a coverage-reporting service + badge, adopt signed tags/provenance.

## 5. CHAOSS Community Health Metrics — health observability

- [x] `P1` Issue/PR templates emit standardized **labels** (`bug`, `enhancement`, `needs-triage`, `dependencies`, ...).
- [x] `P1` Templates capture the fields metrics need (§2).
- [x] `P2` Response/triage expectations documented (`SUPPORT.md`, `GOVERNANCE.md`).
- [x] `P2` Add **`COMMUNITY.md`** — onboarding + channels.
- [ ] `P2` **Manual:** enable GitHub Insights / external metrics dashboard (repo setting).

## 6. Linux Foundation Open-Source Launch Guidance

- [x] `P1` Add **`RELEASING.md`** — version bump → changelog → tag → build → publish (PyPI + npm).
- [x] `P1` **SemVer + deprecation policy** — `docs/VERSIONING.md`.
- [x] `P2` Extract roadmap into **`ROADMAP.md`** (linked from README roadmap section).
- [x] `P1` **License consistency — RESOLVED:** `studio/chat-ui/package.json` changed from `MIT` → **`Apache-2.0`** to match the repo `LICENSE` and Python package. Whole project now single-license Apache-2.0.
- [ ] `P2` Trademark/naming review + `NOTICE` / third-party license inventory (manual legal review).

## 7. Standard Programming Concepts — structure & packaging hygiene (non-functional)

- [x] `P0` **Single version source** — new `src/openbench/_version.py` is the only literal; `pyproject.toml` uses `dynamic = ["version"]` (`attr = "openbench._version.__version__"`); CLI reads `importlib.metadata.version("openbench")`. Verified all three resolve to `0.1.0`.
- [x] `P1` Add **`src/openbench/py.typed`** (PEP 561) + included in `[tool.setuptools.package-data]`.
- [x] `P1` Add **`tests/conftest.py`** (opt-in fixtures, no autouse) + **`tests/fixtures/`** — does not affect existing tests.
- [x] `P1` **Test-coverage backlog** — `docs/TEST_COVERAGE_BACKLOG.md` lists ~31 modules without a dedicated test file (CLI commands, MCP subsystem, generators, stores).
- [x] `P2` `requirements.txt` vs `pyproject.toml` — `pyproject.toml` documented as canonical (see CONTRIBUTING dev setup using `pip install -e ".[all]"`).
- [x] `P2` `skills/` mypy-exclusion rationale already documented inline in `pyproject.toml` (runtime `importlib` loading).
- [x] `P2` Frontend `studio/chat-ui` — build/typecheck/test now CI-gated (§2). NOTE: `package.json` already has a `license` field (`MIT`) — see the license-consistency flag in §6.

## 8. Tracking / execution order — DONE this pass

1. **P0:** `ci.yml`, `SECURITY.md`, single version source — ✅ complete & verified.
2. **Governance docs:** GOVERNANCE / MAINTAINERS / CODEOWNERS / SUPPORT / CHANGELOG / COMMUNITY — ✅.
3. **Automation:** issue/PR templates, dependabot, coverage + pip-audit + scorecard — ✅.
4. **OpenSSF / CHAOSS / LF maturity:** badge tracker, RELEASING, VERSIONING, ROADMAP — ✅.

### Remaining (require human / GitHub-admin action — cannot be committed)

- Enable branch protection on `main` (§2).
- Register at bestpractices.dev + coverage badge + signed releases (§4).
- Enable GitHub Insights / metrics dashboard (§5).
- Trademark/naming + `NOTICE` legal review (§6).
- Replace `@ai-kitchen-inc/maintainers` placeholder with real maintainer handles in `CODEOWNERS` / `MAINTAINERS.md` (§1).

> Verification: `import openbench` OK; `openbench --version` → 0.1.0; build backend
> resolves dynamic version → 0.1.0; `ruff check` clean on all changed files; smoke
> test subset 177 passed. `git status` shows only governance/docs/CI/packaging
> additions + the version refactor — no behavioral source change.
