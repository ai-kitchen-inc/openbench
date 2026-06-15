"""Shared pytest fixtures for the OpenBench test suite.

These fixtures are opt-in (none are ``autouse``) so existing tests — including
the ``unittest``-style ones discovered by ``python -m unittest`` — are
unaffected. Import a fixture simply by adding its name as a test argument.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# Directory holding static test data files (CSV, JSON, PDF samples, ...).
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the ``tests/fixtures`` directory."""
    return FIXTURES_DIR


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Return an isolated temporary working directory for a test.

    Built on pytest's ``tmp_path`` so cleanup is automatic. Use this for tests
    that write files (checkpoints, exports, scratchpads) without polluting the
    repository.
    """
    return tmp_path


@pytest.fixture
def no_provider_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear common LLM/provider API-key env vars for hermetic tests.

    Ensures a test does not accidentally pick up real credentials from the
    developer's environment and make live API calls.
    """
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "TAVILY_API_KEY",
        "PINECONE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Guard against the test runner inheriting a configured key file path.
    monkeypatch.delenv("OPENBENCH_CONFIG", raising=False)
    yield
    # monkeypatch restores the environment automatically.


@pytest.fixture
def chdir_tmp(tmp_path: Path) -> Iterator[Path]:
    """Temporarily change the working directory to a fresh temp dir."""
    prev = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)
