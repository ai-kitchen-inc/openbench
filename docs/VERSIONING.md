# Versioning & Deprecation Policy

OpenBench follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## Version format

`MAJOR.MINOR.PATCH`

- **MAJOR** — incompatible public API changes.
- **MINOR** — backwards-compatible functionality added.
- **PATCH** — backwards-compatible bug fixes.

## Pre-1.0 caveat

While OpenBench is in the `0.x` series (alpha), the public API may change
between minor versions. We will still document breaking changes in
[CHANGELOG.md](../CHANGELOG.md) and call them out in release notes.

## Single source of truth

The version is defined in exactly one place:
[`src/openbench/_version.py`](../src/openbench/_version.py).

- `pyproject.toml` derives it dynamically
  (`[tool.setuptools.dynamic] version = {attr = "openbench._version.__version__"}`).
- The CLI reads it at runtime from the installed package metadata
  (`importlib.metadata.version("openbench")`), falling back to `_version.py`
  when running from a source tree.

To bump the version, edit `_version.py` only. See [RELEASING.md](../RELEASING.md).

## What counts as the public API

The public, SemVer-protected surface is what is exported from
`openbench.__all__` and the documented subpackage `__all__` lists. Names
prefixed with an underscore, modules under `openbench.skills` internals, and
anything explicitly marked experimental are **not** covered by SemVer.

## Deprecation policy

When a public API needs to change:

1. Mark the old behavior as deprecated in the code (emit
   `DeprecationWarning`) and in the docstring.
2. Document it in the changelog under a **Deprecated** heading.
3. Keep the deprecated API working for at least **one minor release** (post
   1.0) before removal.
4. Remove it only in a MAJOR release (post 1.0), noting the removal in the
   changelog under **Removed**.

## Supported versions

See [SECURITY.md](../SECURITY.md) for which versions receive security fixes.
