"""Single source of truth for the OpenBench package version.

This module intentionally contains no imports so that build backends
(setuptools ``dynamic = ["version"]`` via ``attr``) can read ``__version__``
statically without importing the full package.

Bump the version here only — ``pyproject.toml`` derives it via
``[tool.setuptools.dynamic]`` and the CLI reads it from the installed
package metadata at runtime.
"""

__version__ = "0.1.0"
