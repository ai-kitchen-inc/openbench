"""Sphinx configuration for the OpenBench documentation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "OpenBench"
author = "OpenBench Contributors"
copyright = "2026, OpenBench Contributors"
release = "0.1.0"
version = release

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "sphinx_click",
    "sphinx_copybutton",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
master_doc = "index"

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

html_theme = "sphinx_rtd_theme"
html_title = "OpenBench Documentation"
html_static_path = ["_static"]
html_show_sourcelink = True
suppress_warnings = [
    # Several existing source docstrings use Markdown fences. They still render,
    # but docutils reports them as reStructuredText warnings during autodoc.
    "docutils",
    # Existing Markdown docs link to RFC scratch files that are not part of the
    # published documentation tree.
    "myst.xref_missing",
    # Public package modules re-export objects from implementation modules.
    "ref.python",
    "misc.highlighting_failure",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "no-index": True,
}
autosummary_generate = True
autodoc_typehints = "description"
autoclass_content = "both"
napoleon_google_docstring = True
napoleon_numpy_docstring = True

# Optional OpenBench integrations are intentionally lazy at runtime. Mock them
# during documentation builds so ReadTheDocs does not need every provider SDK.
autodoc_mock_imports = [
    "ag_ui",
    "anthropic",
    "autogen",
    "chromadb",
    "crewai",
    "e2b",
    "firebase_admin",
    "google",
    "google_auth_oauthlib",
    "googleapiclient",
    "langchain",
    "langextract",
    "matplotlib",
    "numpy",
    "openai",
    "pandas",
    "pinecone",
    "pptx",
    "pypdf",
    "reportlab",
    "tavily",
]

# Keep local Windows builds readable even when a terminal defaults to a legacy
# code page. This also helps sphinx-click render Click help with icons.
os.environ.setdefault("PYTHONUTF8", "1")
