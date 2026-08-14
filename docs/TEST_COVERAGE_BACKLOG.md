# Test Coverage Backlog

Tracked list of source modules that currently lack a dedicated test file. This
is a living backlog — pick an item, add `tests/test_<module>.py`, and remove it
from this list in the same PR. Use the shared fixtures in
[`tests/conftest.py`](../tests/conftest.py).

> Generated heuristically (module stem vs. `tests/test_*.py` names). Some
> modules below are exercised indirectly — e.g. the SDK skills' `tools.py`
> files are covered by `tests/test_sdk_skills.py`, and `_version.py` is trivial.
> Verify with `pytest --cov=openbench --cov-report=term-missing` before assuming
> a module is untested.

## High value (public behavior, no direct test)

- [ ] `src/openbench/cli/commands/init.py`
- [ ] `src/openbench/cli/commands/data.py`
- [ ] `src/openbench/cli/commands/generate.py`
- [ ] `src/openbench/cli/commands/models.py`
- [ ] `src/openbench/cli/commands/project.py`
- [ ] `src/openbench/cli/commands/tools.py`
- [ ] `src/openbench/cli/main.py`
- [ ] `src/openbench/output/generators.py`
- [ ] `src/openbench/data/stores/pinecone.py`
- [ ] `src/openbench/chat/stores/sqlite.py`
- [ ] `src/openbench/chat/transport/sessions.py`

## MCP subsystem

- [ ] `src/openbench/mcp/adapters.py`
- [ ] `src/openbench/mcp/observability.py`

## Integrations & misc

- [ ] `src/openbench/integrations/gdrive/_etag_cache.py`
- [ ] `src/openbench/integrations/gdrive/_pending_sync_worker.py`
- [ ] `src/openbench/intelligence/scratchpads/local_md.py`

## Likely already covered indirectly (confirm, then drop)

- [ ] `src/openbench/skills/*/tools.py` — covered by `tests/test_sdk_skills.py`
- [ ] `src/openbench/_version.py` — trivial constant; covered by version checks

## Goal

Per [CONTRIBUTING.md](../CONTRIBUTING.md), new code targets **80%+** coverage.
Track overall coverage in CI (`pytest --cov=openbench`) and wire a coverage
badge once a reporting service is connected (see
[OPENSSF_BADGE.md](OPENSSF_BADGE.md)).
